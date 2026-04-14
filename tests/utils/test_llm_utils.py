import asyncio
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from openjiuwen_deepsearch.utils.common_utils.llm_utils import (
    _install_usage_only_chunk_parser,
    ainvoke_llm_with_stats,
    add_workflow_llm_usage,
    get_workflow_llm_usage,
    pop_workflow_llm_usage,
    reset_workflow_llm_usage,
    save_workflow_llm_usage_to_session,
)


class _DummyModelConfig:
    """模拟 LLM 模型配置对象。"""

    def __init__(self, stream_options=None):
        """初始化模拟配置。

        Args:
            stream_options (dict | None): 预置的流式配置参数。
        """
        self.stream_options = stream_options

    def model_dump(self):
        """导出模拟配置字典。

        Returns:
            包含 stream_options 的配置字典。
        """
        if self.stream_options is None:
            return {}
        return {"stream_options": self.stream_options}


class _DummyModel:
    """模拟 openjiuwen 的 Model 对象。"""

    def __init__(self, stream_options=None):
        """初始化模拟模型。

        Args:
            stream_options (dict | None): 预置的流式配置参数。
        """
        self.model_config = _DummyModelConfig(stream_options=stream_options)


class _FakeResponse:
    """模拟 LLM 响应对象。"""

    def __init__(self, content="ok", usage_metadata=None):
        """初始化模拟响应。

        Args:
            content (str): 模型响应文本内容。
            usage_metadata (dict | None): token usage 元数据。
        """
        self.content = content
        self.usage_metadata = usage_metadata or {}

    def model_dump(self):
        """导出统一响应结构。

        Returns:
            与业务代码兼容的最小响应字典。
        """
        return {"content": self.content, "tool_calls": None}


@pytest.mark.asyncio
async def test_ainvoke_enables_include_usage_when_stats_llm_enabled():
    """验证开启 stats_info_llm 时会注入 include_usage。"""
    llm_obj = {"model": _DummyModel(), "model_name": "demo-model"}
    fake_config = SimpleNamespace(agent_config=SimpleNamespace(stats_info_llm=True))

    with patch(
        "openjiuwen_deepsearch.utils.common_utils.llm_utils.Config",
        return_value=fake_config,
    ), patch(
        "openjiuwen_deepsearch.utils.common_utils.llm_utils.llm_astream",
        new=AsyncMock(return_value=_FakeResponse(usage_metadata={"input_tokens": 1, "output_tokens": 2})),
    ) as mock_llm_astream:
        await ainvoke_llm_with_stats(
            llm=llm_obj,
            messages=[{"role": "user", "content": "hello"}],
            agent_name="entry",
        )

    called_kwargs = mock_llm_astream.await_args.kwargs
    assert called_kwargs["stream_options"]["include_usage"] is True


@pytest.mark.asyncio
async def test_ainvoke_merges_existing_stream_options_when_stats_enabled():
    """验证 include_usage 注入时不会覆盖已有 stream_options。"""
    llm_obj = {
        "model": _DummyModel(stream_options={"existing_key": "existing_value", "include_usage": False}),
        "model_name": "demo-model",
    }
    fake_config = SimpleNamespace(agent_config=SimpleNamespace(stats_info_llm=True))

    with patch(
        "openjiuwen_deepsearch.utils.common_utils.llm_utils.Config",
        return_value=fake_config,
    ), patch(
        "openjiuwen_deepsearch.utils.common_utils.llm_utils.llm_astream",
        new=AsyncMock(return_value=_FakeResponse(usage_metadata={"input_tokens": 1, "output_tokens": 2})),
    ) as mock_llm_astream:
        await ainvoke_llm_with_stats(
            llm=llm_obj,
            messages=[{"role": "user", "content": "hello"}],
            agent_name="entry",
        )

    stream_options = mock_llm_astream.await_args.kwargs["stream_options"]
    assert stream_options["existing_key"] == "existing_value"
    assert stream_options["include_usage"] is True


@pytest.mark.asyncio
async def test_ainvoke_stats_total_tokens_use_total_tokens_field():
    """验证统计中的 total_tokens 使用正确字段。"""
    llm_obj = {"model": _DummyModel(), "model_name": "demo-model"}
    fake_config = SimpleNamespace(agent_config=SimpleNamespace(stats_info_llm=True))

    with patch(
        "openjiuwen_deepsearch.utils.common_utils.llm_utils.Config",
        return_value=fake_config,
    ), patch(
        "openjiuwen_deepsearch.utils.common_utils.llm_utils.llm_astream",
        new=AsyncMock(
            return_value=_FakeResponse(
                usage_metadata={
                    "input_tokens": 11,
                    "output_tokens": 22,
                    "total_tokens": 44,
                    "total_latency": 12345,
                }
            )
        ),
    ), patch(
        "openjiuwen_deepsearch.utils.common_utils.llm_utils.metrics_logger.info",
    ) as mock_metrics_info:
        await ainvoke_llm_with_stats(
            llm=llm_obj,
            messages=[{"role": "user", "content": "hello"}],
            agent_name="entry",
        )

    assert mock_metrics_info.call_count == 1
    logged_line = mock_metrics_info.call_args.args[0]
    assert "'total_tokens': 44" in logged_line


@pytest.mark.asyncio
async def test_ainvoke_does_not_force_include_usage_when_stats_disabled():
    """验证关闭 stats_info_llm 时不会强制注入 include_usage。"""
    llm_obj = {
        "model": _DummyModel(stream_options={"existing_key": "existing_value"}),
        "model_name": "demo-model",
    }
    fake_config = SimpleNamespace(agent_config=SimpleNamespace(stats_info_llm=False))

    with patch(
        "openjiuwen_deepsearch.utils.common_utils.llm_utils.Config",
        return_value=fake_config,
    ), patch(
        "openjiuwen_deepsearch.utils.common_utils.llm_utils.llm_astream",
        new=AsyncMock(return_value=_FakeResponse()),
    ) as mock_llm_astream:
        await ainvoke_llm_with_stats(
            llm=llm_obj,
            messages=[{"role": "user", "content": "hello"}],
            agent_name="entry",
        )

    called_kwargs = mock_llm_astream.await_args.kwargs
    assert called_kwargs["stream_options"] is None


@pytest.mark.asyncio
async def test_ainvoke_prefers_session_stats_flag_over_global_default():
    """验证会话中的 stats_info_llm 配置优先生效。"""
    llm_obj = {"model": _DummyModel(), "model_name": "demo-model"}
    fake_config = SimpleNamespace(agent_config=SimpleNamespace(stats_info_llm=False))
    fake_session = SimpleNamespace(get_global_state=lambda key: True if key == "config.stats_info_llm" else None)

    from openjiuwen_deepsearch.utils.constants_utils.session_contextvars import session_context
    token = session_context.set(fake_session)
    try:
        with patch(
            "openjiuwen_deepsearch.utils.common_utils.llm_utils.Config",
            return_value=fake_config,
        ), patch(
            "openjiuwen_deepsearch.utils.common_utils.llm_utils.llm_astream",
            new=AsyncMock(return_value=_FakeResponse(usage_metadata={"input_tokens": 1, "output_tokens": 2})),
        ) as mock_llm_astream:
            await ainvoke_llm_with_stats(
                llm=llm_obj,
                messages=[{"role": "user", "content": "hello"}],
                agent_name="entry",
            )
    finally:
        session_context.reset(token)

    called_kwargs = mock_llm_astream.await_args.kwargs
    assert called_kwargs["stream_options"]["include_usage"] is True


def test_workflow_llm_usage_can_accumulate_and_pop():
    """验证 workflow 级 token 统计可以累加并清理。"""
    thread_id = "workflow-usage-case"
    reset_workflow_llm_usage(thread_id)

    add_workflow_llm_usage(thread_id, input_tokens=3, output_tokens=5, total_tokens=8, agent_name="entry")
    add_workflow_llm_usage(thread_id, input_tokens=7, output_tokens=11, total_tokens=18, agent_name="entry")
    add_workflow_llm_usage(thread_id, input_tokens=2, output_tokens=3, total_tokens=5, agent_name="reporter")

    usage = get_workflow_llm_usage(thread_id)
    assert usage == {
        "input_tokens": 12,
        "output_tokens": 19,
        "total_tokens": 31,
        "llm_call_count": 3,
        "agent_name_token_usage": [
            {
                "agent_name": "entry",
                "input_tokens": 10,
                "output_tokens": 16,
                "total_tokens": 26,
                "llm_call_count": 2,
            },
            {
                "agent_name": "reporter",
                "input_tokens": 2,
                "output_tokens": 3,
                "total_tokens": 5,
                "llm_call_count": 1,
            },
        ],
    }

    popped = pop_workflow_llm_usage(thread_id)
    assert popped == usage
    assert get_workflow_llm_usage(thread_id) == {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "llm_call_count": 0,
        "agent_name_token_usage": [],
    }


@pytest.mark.asyncio
async def test_workflow_llm_usage_is_stable_under_coroutine_concurrency():
    """验证协程并发累加场景下 workflow 级 token 统计结果正确。"""
    thread_id = "workflow-usage-concurrency"
    reset_workflow_llm_usage(thread_id)
    workers = 10
    rounds = 100

    async def _worker() -> None:
        """执行单个并发 worker 的累加逻辑。"""
        for _ in range(rounds):
            add_workflow_llm_usage(
                session_id=thread_id,
                input_tokens=1,
                output_tokens=2,
                total_tokens=3,
                agent_name="entry",
            )
            # 主动让出事件循环，模拟 workflow 节点并发调度下的交错调用。
            await asyncio.sleep(0)

    await asyncio.gather(*[_worker() for _ in range(workers)])

    usage = get_workflow_llm_usage(thread_id)
    expected_calls = workers * rounds
    assert usage == {
        "input_tokens": expected_calls,
        "output_tokens": expected_calls * 2,
        "total_tokens": expected_calls * 3,
        "llm_call_count": expected_calls,
        "agent_name_token_usage": [
            {
                "agent_name": "entry",
                "input_tokens": expected_calls,
                "output_tokens": expected_calls * 2,
                "total_tokens": expected_calls * 3,
                "llm_call_count": expected_calls,
            }
        ],
    }
    pop_workflow_llm_usage(thread_id)


@pytest.mark.asyncio
async def test_ainvoke_can_resume_workflow_usage_from_session_snapshot():
    """验证跨进程恢复时可从 session 快照继续累计。"""
    llm_obj = {"model": _DummyModel(), "model_name": "demo-model"}
    fake_config = SimpleNamespace(agent_config=SimpleNamespace(stats_info_llm=False))
    snapshot_usage = {
        "input_tokens": 10,
        "output_tokens": 20,
        "total_tokens": 30,
        "llm_call_count": 4,
        "agent_name_token_usage": [
            {
                "agent_name": "entry",
                "input_tokens": 10,
                "output_tokens": 20,
                "total_tokens": 30,
                "llm_call_count": 4,
            }
        ],
    }

    def _get_global_state(key):
        if key == "config.stats_info_llm":
            return True
        if key == "search_context.final_result.workflow_llm_token_usage":
            return snapshot_usage
        return None

    fake_session = SimpleNamespace(get_global_state=_get_global_state)

    from openjiuwen_deepsearch.utils.constants_utils.session_contextvars import session_context
    from openjiuwen_deepsearch.utils.log_utils.log_common import session_id_ctx
    thread_id = "resume-workflow-usage"

    pop_workflow_llm_usage(thread_id)
    session_token = session_context.set(fake_session)
    thread_token = session_id_ctx.set(thread_id)
    try:
        with patch(
            "openjiuwen_deepsearch.utils.common_utils.llm_utils.Config",
            return_value=fake_config,
        ), patch(
            "openjiuwen_deepsearch.utils.common_utils.llm_utils.llm_astream",
            new=AsyncMock(return_value=_FakeResponse(usage_metadata={"input_tokens": 1, "output_tokens": 2})),
        ):
            await ainvoke_llm_with_stats(
                llm=llm_obj,
                messages=[{"role": "user", "content": "hello"}],
                agent_name="entry",
            )
    finally:
        session_context.reset(session_token)
        session_id_ctx.reset(thread_token)

    usage = get_workflow_llm_usage(thread_id)
    assert usage == {
        "input_tokens": 11,
        "output_tokens": 22,
        "total_tokens": 33,
        "llm_call_count": 5,
        "agent_name_token_usage": [
            {
                "agent_name": "entry",
                "input_tokens": 11,
                "output_tokens": 22,
                "total_tokens": 33,
                "llm_call_count": 5,
            }
        ],
    }
    pop_workflow_llm_usage(thread_id)


def test_save_workflow_llm_usage_to_session_writes_snapshot():
    """验证可将当前 workflow token 累计写入 session。"""
    thread_id = "save-workflow-usage"
    reset_workflow_llm_usage(thread_id)
    add_workflow_llm_usage(thread_id, input_tokens=2, output_tokens=3, total_tokens=5, agent_name="entry")
    captured = {}

    class _FakeSession:
        """模拟 session 对象。"""

        def update_global_state(self, data):
            """记录 update_global_state 入参。"""
            captured.update(data)

    usage = save_workflow_llm_usage_to_session(_FakeSession(), thread_id)
    assert usage == {
        "input_tokens": 2,
        "output_tokens": 3,
        "total_tokens": 5,
        "llm_call_count": 1,
        "agent_name_token_usage": [
            {
                "agent_name": "entry",
                "input_tokens": 2,
                "output_tokens": 3,
                "total_tokens": 5,
                "llm_call_count": 1,
            }
        ],
    }
    assert captured["search_context.final_result.workflow_llm_token_usage"] == usage
    pop_workflow_llm_usage(thread_id)


def test_install_usage_only_chunk_parser_can_recover_usage_chunk():
    """验证单次调用级 parser 补偿能解析 usage-only chunk。"""

    class _FakeClient:
        """模拟底层 client。"""

        def _parse_stream_chunk(self, raw_chunk):
            """模拟原始 parser：usage-only chunk 会被直接忽略。"""
            return None

    fake_model = SimpleNamespace(
        _client=_FakeClient(),
        model_config=SimpleNamespace(model_name="demo-model"),
    )
    restore = _install_usage_only_chunk_parser(fake_model)
    assert callable(restore)

    usage_only_chunk = SimpleNamespace(
        choices=[],
        usage=SimpleNamespace(prompt_tokens=7, completion_tokens=9, total_tokens=16),
    )
    parsed_chunk = fake_model._client._parse_stream_chunk(usage_only_chunk)
    assert parsed_chunk is not None
    assert parsed_chunk.usage_metadata is not None
    assert parsed_chunk.usage_metadata.input_tokens == 7
    assert parsed_chunk.usage_metadata.output_tokens == 9
    assert parsed_chunk.usage_metadata.total_tokens == 16

    restore()


def test_install_usage_only_chunk_parser_is_safe_for_nested_restore():
    """验证同一 client 的嵌套安装/恢复不会提前卸载 parser 补偿。"""

    class _FakeClient:
        """模拟底层 client。"""

        def _parse_stream_chunk(self, raw_chunk):
            """模拟原始 parser：usage-only chunk 会被直接忽略。"""
            return None

    fake_model = SimpleNamespace(
        _client=_FakeClient(),
        model_config=SimpleNamespace(model_name="demo-model"),
    )
    original_parser = fake_model._client._parse_stream_chunk
    usage_only_chunk = SimpleNamespace(
        choices=[],
        usage=SimpleNamespace(prompt_tokens=3, completion_tokens=5, total_tokens=8),
    )

    restore_outer = _install_usage_only_chunk_parser(fake_model)
    restore_inner = _install_usage_only_chunk_parser(fake_model)

    restore_outer()
    parsed_chunk = fake_model._client._parse_stream_chunk(usage_only_chunk)
    assert parsed_chunk is not None
    assert parsed_chunk.usage_metadata.total_tokens == 8

    restore_inner()
    assert getattr(fake_model._client._parse_stream_chunk, "__func__", None) is getattr(original_parser, "__func__", None)
