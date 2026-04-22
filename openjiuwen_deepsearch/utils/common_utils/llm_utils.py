# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2025. All rights reserved.

import asyncio
import copy
import json
import logging
import re
import time
import uuid
from typing import Sequence, Any

import json_repair
from openjiuwen.core.foundation.llm.schema.message import (
    UserMessage,
    SystemMessage,
    AssistantMessage,
    ToolMessage,
    UsageMetadata,
)
from openjiuwen.core.foundation.llm.schema.message_chunk import AssistantMessageChunk
from pydantic import BaseModel

from openjiuwen_deepsearch.common.common_constants import MAX_LLM_RESP_LENGTH
from openjiuwen_deepsearch.common.exception import CustomValueException
from openjiuwen_deepsearch.common.status_code import StatusCode
from openjiuwen_deepsearch.config.config import Config
from openjiuwen_deepsearch.framework.openjiuwen.agent.search_context import Message
from openjiuwen_deepsearch.utils.common_utils.stream_utils import get_current_time, MessageType, StreamEvent
from openjiuwen_deepsearch.utils.constants_utils.session_contextvars import session_context, cancel_context
from openjiuwen_deepsearch.utils.log_utils.log_common import session_id_ctx
from openjiuwen_deepsearch.utils.log_utils.log_manager import LogManager
from openjiuwen_deepsearch.utils.log_utils.log_metrics import metrics_logger, TIME_LOGGER_TAG

logger = logging.getLogger(__name__)
_WORKFLOW_LLM_USAGE: dict[str, dict[str, Any]] = {}
_USAGE_ONLY_PARSER_PATCHES: dict[int, dict[str, Any]] = {}


def _normalize_agent_name(agent_name: Any) -> str:
    """标准化 agent_name 字段。

    Args:
        agent_name (Any): 原始 agent_name 值。

    Returns:
        str: 标准化后的 agent_name；为空时返回 "unknown"。
    """
    if not isinstance(agent_name, str):
        return "unknown"
    normalized_name = agent_name.strip()
    return normalized_name if normalized_name else "unknown"


def _build_empty_agent_name_usage(agent_name: str) -> dict[str, Any]:
    """构造单个 agent_name 的空 token 统计结构。

    Args:
        agent_name (str): 调用方标识。

    Returns:
        dict[str, Any]: 单 agent 的空统计结构。
    """
    return {
        "agent_name": _normalize_agent_name(agent_name),
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "llm_call_count": 0,
    }


def _merge_agent_name_usage_list(agent_usage_list: Any) -> list[dict[str, Any]]:
    """合并并规范化 agent_name 级 token 统计列表。

    Args:
        agent_usage_list (Any): 待处理的 agent 统计列表。

    Returns:
        list[dict[str, Any]]: 去重并聚合后的统计列表。
    """
    if not isinstance(agent_usage_list, list):
        return []
    merged_usage: dict[str, dict[str, Any]] = {}
    for usage_item in agent_usage_list:
        if not isinstance(usage_item, dict):
            continue
        normalized_name = _normalize_agent_name(usage_item.get("agent_name"))
        current_usage = merged_usage.setdefault(normalized_name, _build_empty_agent_name_usage(normalized_name))
        current_usage["input_tokens"] += _to_non_negative_int(usage_item.get("input_tokens", 0))
        current_usage["output_tokens"] += _to_non_negative_int(usage_item.get("output_tokens", 0))
        current_usage["total_tokens"] += _to_non_negative_int(usage_item.get("total_tokens", 0))
        current_usage["llm_call_count"] += _to_non_negative_int(usage_item.get("llm_call_count", 0))
    return list(merged_usage.values())


def _build_empty_workflow_llm_usage() -> dict[str, Any]:
    """构造空的 workflow 级 token 统计结构。

    Returns:
        dict[str, Any]: 空统计结构，包含总量和 agent_name 统计字段。
    """
    return {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "llm_call_count": 0,
        "agent_name_token_usage": [],
    }


def normalize_workflow_llm_usage(usage: Any) -> dict[str, Any]:
    """标准化 workflow 级 token 统计结构。

    Args:
        usage (Any): 待标准化的数据，可为 dict 或任意类型。

    Returns:
        dict[str, Any]: 规范后的统计结构，包含总量统计和 agent_name 维度统计。
    """
    if not isinstance(usage, dict):
        return _build_empty_workflow_llm_usage()
    return {
        "input_tokens": _to_non_negative_int(usage.get("input_tokens", 0)),
        "output_tokens": _to_non_negative_int(usage.get("output_tokens", 0)),
        "total_tokens": _to_non_negative_int(usage.get("total_tokens", 0)),
        "llm_call_count": _to_non_negative_int(usage.get("llm_call_count", 0)),
        "agent_name_token_usage": _merge_agent_name_usage_list(usage.get("agent_name_token_usage", [])),
    }


def is_workflow_llm_usage_empty(usage: dict[str, Any]) -> bool:
    """判断 workflow 级 token 统计是否为空。

    Args:
        usage (dict[str, Any]): token 统计结构。

    Returns:
        bool: 全字段为 0 返回 True。
    """
    normalized_usage = normalize_workflow_llm_usage(usage)
    return (
        normalized_usage["input_tokens"] == 0
        and normalized_usage["output_tokens"] == 0
        and normalized_usage["total_tokens"] == 0
        and normalized_usage["llm_call_count"] == 0
        and len(normalized_usage["agent_name_token_usage"]) == 0
    )


def _ensure_workflow_llm_usage_initialized(session_id: str, session: Any = None) -> None:
    """确保指定 workflow 的本地累计状态已初始化。

    该方法用于跨进程恢复场景：当本地内存没有 session_id 对应累计时，尝试从
    session 全局状态中的 `search_context.final_result.workflow_llm_token_usage` 恢复。

    Args:
        session_id (str): workflow 对应会话 ID。
        session (Any): 当前会话对象，需支持 get_global_state 方法。
    """
    if not session_id or session_id == "-":
        return

    current_usage = _WORKFLOW_LLM_USAGE.get(session_id)
    if current_usage is not None and not is_workflow_llm_usage_empty(current_usage):
        return

    restored_usage = _build_empty_workflow_llm_usage()
    if session is not None:
        try:
            snapshot = session.get_global_state("search_context.final_result.workflow_llm_token_usage")
            restored_usage = normalize_workflow_llm_usage(snapshot)
        except Exception:
            # 兜底保护：恢复失败时不影响主流程，按空统计继续。
            restored_usage = _build_empty_workflow_llm_usage()

    _WORKFLOW_LLM_USAGE[session_id] = restored_usage


def get_effective_workflow_llm_usage(session_id: str, session: Any = None) -> dict[str, Any]:
    """获取当前 workflow 的有效 token 汇总快照。

    优先返回本地内存中的累计统计；当本地为空时，回退读取 session 中持久化的
    `search_context.final_result.workflow_llm_token_usage`，以覆盖 HITL 恢复等场景。

    Args:
        session_id (str): workflow 对应会话 ID。
        session (Any): 当前会话对象，需支持 get_global_state 方法；为空时仅返回本地累计。

    Returns:
        dict[str, Any]: 当前有效统计快照。
    """
    local_usage = normalize_workflow_llm_usage(get_workflow_llm_usage(session_id))
    if session is None or not is_workflow_llm_usage_empty(local_usage):
        return local_usage

    try:
        persisted_usage = normalize_workflow_llm_usage(
            session.get_global_state("search_context.final_result.workflow_llm_token_usage")
        )
    except Exception:
        persisted_usage = _build_empty_workflow_llm_usage()

    if not is_workflow_llm_usage_empty(persisted_usage):
        return persisted_usage
    return local_usage


def save_workflow_llm_usage_to_session(session: Any, session_id: str) -> dict[str, Any]:
    """将 workflow 级 token 累计落盘到 session 全局状态。

    Args:
        session (Any): 当前会话对象，需支持 update_global_state 方法。
        session_id (str): workflow 对应会话 ID。

    Returns:
        dict[str, Any]: 当前累计统计快照。
    """
    usage = get_effective_workflow_llm_usage(session_id=session_id, session=session)
    if session is None:
        return usage
    try:
        session.update_global_state({"search_context.final_result.workflow_llm_token_usage": usage})
    except Exception:
        # 持久化失败时仅降级，不影响主流程执行。
        pass
    return usage


def add_workflow_llm_usage(
    session_id: str,
    input_tokens: int,
    output_tokens: int,
    total_tokens: int,
    agent_name: str = "",
) -> None:
    """累加指定 workflow 的 LLM token 消耗。

    Args:
        session_id (str): workflow 对应会话 ID。
        input_tokens (int): 本次调用输入 token 数。
        output_tokens (int): 本次调用输出 token 数。
        total_tokens (int): 本次调用总 token 数。
        agent_name (str): 本次调用的 agent 名称。
    """
    if not session_id or session_id == "-":
        return

    usage = _WORKFLOW_LLM_USAGE.setdefault(session_id, _build_empty_workflow_llm_usage())
    usage["input_tokens"] += _to_non_negative_int(input_tokens)
    usage["output_tokens"] += _to_non_negative_int(output_tokens)
    usage["total_tokens"] += _to_non_negative_int(total_tokens)
    usage["llm_call_count"] += 1
    if agent_name:
        normalized_name = _normalize_agent_name(agent_name)
        agent_usage_list = usage.setdefault("agent_name_token_usage", [])
        if not isinstance(agent_usage_list, list):
            agent_usage_list = []
            usage["agent_name_token_usage"] = agent_usage_list
        target_usage = None
        for usage_item in agent_usage_list:
            if isinstance(usage_item, dict) and usage_item.get("agent_name") == normalized_name:
                target_usage = usage_item
                break
        if target_usage is None:
            target_usage = _build_empty_agent_name_usage(normalized_name)
            agent_usage_list.append(target_usage)
        target_usage["input_tokens"] += _to_non_negative_int(input_tokens)
        target_usage["output_tokens"] += _to_non_negative_int(output_tokens)
        target_usage["total_tokens"] += _to_non_negative_int(total_tokens)
        target_usage["llm_call_count"] += 1


def get_workflow_llm_usage(session_id: str) -> dict[str, Any]:
    """获取指定 workflow 的 LLM token 汇总信息。

    Args:
        session_id (str): workflow 对应会话 ID。

    Returns:
        dict[str, Any]: 汇总统计；若不存在返回全 0 结构。
    """
    if not session_id or session_id == "-":
        return _build_empty_workflow_llm_usage()
    usage = _WORKFLOW_LLM_USAGE.get(session_id)
    if usage is None:
        return _build_empty_workflow_llm_usage()
    return copy.deepcopy(usage)


def pop_workflow_llm_usage(session_id: str) -> dict[str, Any]:
    """弹出并返回指定 workflow 的 LLM token 汇总信息。

    Args:
        session_id (str): workflow 对应会话 ID。

    Returns:
        dict[str, Any]: 汇总统计；若不存在返回全 0 结构。
    """
    if not session_id or session_id == "-":
        return _build_empty_workflow_llm_usage()
    usage = _WORKFLOW_LLM_USAGE.pop(session_id, None)
    if usage is None:
        return _build_empty_workflow_llm_usage()
    return usage


def _to_non_negative_int(value: Any, default: int = 0) -> int:
    """将任意数值安全转换为非负整数。

    Args:
        value (Any): 待转换值，支持 int/float/str 等可转为数字的类型。
        default (int): 转换失败时的默认值。

    Returns:
        int: 非负整数；转换失败时返回 default。
    """
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return default


def _to_dict_safe(value: Any) -> dict[str, Any]:
    """将对象安全转换为字典。

    Args:
        value (Any): 任意对象，可能为 ``dict``、Pydantic 模型或普通对象。

    Returns:
        dict[str, Any]: 可用字典；转换失败时返回空字典。
    """
    if isinstance(value, dict):
        return value
    if isinstance(value, BaseModel):
        return value.model_dump()
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            dumped = model_dump()
        except Exception:
            return {}
        return dumped if isinstance(dumped, dict) else {}
    value_dict = getattr(value, "__dict__", None)
    if isinstance(value_dict, dict):
        return value_dict
    return {}


def _extract_usage_tokens(usage_payload: Any) -> tuple[int, int, int]:
    """从多种 usage 结构中提取输入、输出、总 token 数。

    Args:
        usage_payload (Any): usage 对象，可能为 dict、Pydantic 模型或 SDK 对象。

    Returns:
        tuple[int, int, int]: ``(input_tokens, output_tokens, total_tokens)``。
    """
    usage = _to_dict_safe(usage_payload)

    # 兼容部分供应商可能返回的嵌套 token_usage 结构。
    token_usage = usage.get("token_usage")
    if isinstance(token_usage, dict):
        merged_usage = dict(token_usage)
        merged_usage.update(usage)
        usage = merged_usage

    input_tokens = _to_non_negative_int(
        usage.get("input_tokens", usage.get("prompt_tokens", usage.get("prompt_token_count", 0)))
    )
    if input_tokens == 0:
        input_tokens = _to_non_negative_int(usage.get("prompt_tokens", usage.get("prompt_token_count", 0)))

    output_tokens = _to_non_negative_int(
        usage.get("output_tokens", usage.get("completion_tokens", usage.get("completion_token_count", 0)))
    )
    if output_tokens == 0:
        output_tokens = _to_non_negative_int(usage.get("completion_tokens", usage.get("completion_token_count", 0)))
    total_tokens = usage.get("total_tokens", usage.get("total_token_count"))
    if total_tokens is None:
        total_tokens = input_tokens + output_tokens
    total_tokens = _to_non_negative_int(total_tokens, default=input_tokens + output_tokens)
    return input_tokens, output_tokens, total_tokens


def _is_llm_stats_enabled() -> bool:
    """判断当前调用是否开启 LLM 调用统计。

    优先级：
    1. 当前会话中的 `config.stats_info_llm`（按单次 workflow 生效）。
    2. 全局默认配置 `Config().agent_config.stats_info_llm`。

    Returns:
        bool: 是否开启 LLM 调用统计。
    """
    try:
        session = session_context.get()
        if session is not None:
            session_flag = session.get_global_state("config.stats_info_llm")
            if session_flag is not None:
                return bool(session_flag)
    except LookupError:
        # 非 workflow 会话场景，走全局默认配置兜底。
        pass
    except Exception:
        # 避免统计开关读取异常影响主流程。
        pass

    return bool(Config().agent_config.stats_info_llm)


def _raise_if_cancelled():
    """
    检查 cancel_context 中的取消事件，如果已设置则抛出 CancelledError。
    
    此函数在 LLM 调用的关键路径（llm_astream / ainvoke_llm_with_stats）中被调用，
    用于及时响应外部取消请求，中断正在进行的 LLM 流式/非流式调用。
    """
    cancel_event = cancel_context.get()
    if cancel_event and cancel_event.is_set():
        logger.info("LLM call cancelled via cancel_event")
        raise asyncio.CancelledError("cancelled")


def messages_to_json(messages: Sequence[Any] | Message) -> str:
    """Dump message to json string."""
    result = []
    if messages is None:
        return ""

    if isinstance(messages, Message):
        result = messages.model_dump()
    else:
        for msg in messages:
            if isinstance(msg, dict):
                result.append(msg)
            elif isinstance(msg, Message):
                result.append(msg.model_dump())
            else:
                result.append(str(msg))
                if not LogManager.is_sensitive():
                    logger.error(f"error message type: {msg}")
                else:
                    logger.error(f"error message type.")

    return json.dumps(result, ensure_ascii=False, indent=4)


def normalize_json_output(input_data: str) -> str:
    """
    规范化 JSON 输出

    Args:
        input_data: 可能包含 JSON 的字符串内容

    Returns:
        str: 规范化的 JSON 字符串，如果不是 JSON, 则为原始内容
    """
    processed = input_data.strip()
    json_signals = ('{', '[', '```json', '```ts')

    if not any(indicator in processed for indicator in json_signals[:2]) and not any(
            marker in processed for marker in json_signals[2:]):
        return processed

    # 处理代码块标记
    code_blocks = {
        'prefixes': ('```json', '```ts'),
        'suffix': '```'
    }
    for prefix in code_blocks['prefixes']:
        if processed.startswith(prefix):
            processed = processed[len(prefix):].lstrip('\n')

    if processed.endswith(code_blocks['suffix']):
        processed = processed[:-len(code_blocks['suffix'])].rstrip('\n')

    # 尝试进行JSON修复和序列化
    try:
        reconstructed = json_repair.loads(processed)
        return json.dumps(reconstructed, ensure_ascii=False)
    except Exception as error:
        if not LogManager.is_sensitive():
            logger.error(f"JSON normalization error: {error}")
        else:
            logger.error(f"JSON normalization error.")
        return input_data.strip()


def _extract_json(text: str) -> str:
    # 去除 ```json 或 ``` 包裹
    return re.sub(r"^```(?:json)?\n|\n```$", "", text.strip())


def _extract_usage_payload_from_stream_chunk(raw_chunk: Any) -> Any:
    """从流式原始 chunk 中提取 usage 载荷。

    Args:
        raw_chunk (Any): 模型客户端收到的原始流式 chunk。

    Returns:
        Any: usage 结构；不存在时返回 ``None``。
    """
    if raw_chunk is None:
        return None
    if hasattr(raw_chunk, "usage"):
        usage_value = getattr(raw_chunk, "usage")
        return usage_value if usage_value else None
    if isinstance(raw_chunk, dict):
        usage_value = raw_chunk.get("usage")
        return usage_value if usage_value else None

    decoded = None
    if isinstance(raw_chunk, (bytes, bytearray)):
        decoded = bytes(raw_chunk).decode("utf-8", errors="ignore").strip()
    elif isinstance(raw_chunk, str):
        decoded = raw_chunk.strip()

    if not decoded:
        return None
    if decoded.startswith("data: "):
        decoded = decoded[6:]
    if decoded == "[DONE]":
        return None

    try:
        parsed_payload = json.loads(decoded)
    except Exception:
        return None
    if not isinstance(parsed_payload, dict):
        return None
    usage_value = parsed_payload.get("usage")
    return usage_value if usage_value else None


def _build_usage_only_chunk(raw_chunk: Any, model_name: str) -> AssistantMessageChunk | None:
    """根据 usage-only chunk 构造可合并的 AssistantMessageChunk。

    Args:
        raw_chunk (Any): 原始流式 chunk。
        model_name (str): 模型名称。

    Returns:
        AssistantMessageChunk | None: 可用于累计 usage 的空内容 chunk；无有效 usage 时返回 ``None``。
    """
    usage_payload = _extract_usage_payload_from_stream_chunk(raw_chunk)
    if usage_payload is None:
        return None

    input_tokens, output_tokens, total_tokens = _extract_usage_tokens(usage_payload)
    if input_tokens == 0 and output_tokens == 0 and total_tokens == 0:
        return None

    return AssistantMessageChunk(
        content="",
        reasoning_content=None,
        tool_calls=None,
        usage_metadata=UsageMetadata(
            model_name=model_name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
        ),
        finish_reason="null",
    )


def _install_usage_only_chunk_parser(llm_model: Any) -> Any:
    """在共享 client 上安装 usage-only chunk 解析器，并返回恢复函数。

    由于同一个 LLM client 可能被多个协程并发复用，这里使用引用计数保证：
    1. 第一个调用负责安装补偿 parser。
    2. 后续嵌套调用仅增加引用计数，不重复覆盖 parser。
    3. 只有最后一个调用结束时才恢复原始 parser。

    Args:
        llm_model (Any): openjiuwen 模型对象，内部包含 ``_client``。

    Returns:
        Any: 可调用恢复函数；不可安装时返回 ``None``。
    """
    client = getattr(llm_model, "_client", None)
    if client is None:
        return None

    original_parser = getattr(client, "_parse_stream_chunk", None)
    if not callable(original_parser):
        return None

    patch_key = id(client)
    patch_state = _USAGE_ONLY_PARSER_PATCHES.get(patch_key)
    if patch_state is None:
        model_name = getattr(getattr(llm_model, "model_config", None), "model_name", "")

        def _patched_parser(raw_chunk: Any):
            parsed_chunk = original_parser(raw_chunk)
            if parsed_chunk is not None:
                return parsed_chunk
            return _build_usage_only_chunk(raw_chunk, model_name=model_name)

        setattr(client, "_parse_stream_chunk", _patched_parser)
        patch_state = {
            "ref_count": 0,
            "original_parser": original_parser,
            "patched_parser": _patched_parser,
        }
        _USAGE_ONLY_PARSER_PATCHES[patch_key] = patch_state
    patch_state["ref_count"] += 1

    def _restore_parser():
        current_state = _USAGE_ONLY_PARSER_PATCHES.get(patch_key)
        if current_state is None:
            return
        current_state["ref_count"] = max(int(current_state.get("ref_count", 0)) - 1, 0)
        if current_state["ref_count"] > 0:
            return
        try:
            setattr(client, "_parse_stream_chunk", current_state["original_parser"])
        except Exception:
            # 恢复失败不影响主流程，避免掩盖业务异常。
            pass
        finally:
            _USAGE_ONLY_PARSER_PATCHES.pop(patch_key, None)

    return _restore_parser


def _resolve_stream_options(llm_model: Any, need_include_usage: bool) -> dict | None:
    """合并模型已有 stream_options，并按需注入 include_usage。

    Args:
        llm_model (Any): LLM 模型实例，可能包含 model_config.stream_options。
        need_include_usage (bool): 是否强制注入 include_usage。

    Returns:
        dict | None: 合并后的 stream_options；若无可用配置则返回 ``None``。
    """
    merged_options: dict = {}
    model_config = getattr(llm_model, "model_config", None)
    if model_config is not None:
        model_dump = getattr(model_config, "model_dump", None)
        if callable(model_dump):
            model_config_dict = model_dump()
            existed_options = model_config_dict.get("stream_options")
            if isinstance(existed_options, dict):
                merged_options.update(existed_options)

    if need_include_usage:
        merged_options["include_usage"] = True

    return merged_options or None


async def llm_astream(*args, **kwargs):
    """以流式方式调用 LLM 并返回完整响应。

    Args:
        llm (Any): LLM 实例。
        messages (list): LLM 输入消息列表。
        model_name (str): 模型名称。
        agent_name (str): 当前调用方名称，用于流输出元信息。
        tools (Any): 本次调用绑定的工具列表。
        need_stream_out (bool): 是否将增量内容写入会话流。
        stream_meta (dict | None): 附加流事件字段。
        stream_options (dict | None): 传入模型 SDK 的流式配置。

    Returns:
        Any: 聚合后的完整 LLM 响应块。
    """
    llm = kwargs.get("llm", args[0] if len(args) > 0 else None)
    messages = kwargs.get("messages", args[1] if len(args) > 1 else None)
    model_name = kwargs.get("model_name", args[2] if len(args) > 2 else None)
    agent_name = kwargs.get("agent_name", args[3] if len(args) > 3 else None)
    tools = kwargs.get("tools", None)
    need_stream_out = kwargs.get("need_stream_out", False)
    stream_meta = kwargs.get("stream_meta", None)
    stream_options = kwargs.get("stream_options", None)

    _raise_if_cancelled()
    full_chunk = None
    can_write_stream = True
    session = None
    try:
        session = session_context.get()
        if session is None:
            can_write_stream = False
            logger.debug(f"session_context not set, can not write to stream")
    except LookupError:
        can_write_stream = False
        logger.debug(f"session_context not set, can not write to stream")

    def _make_payload(message_id: str, event: str, content: str = "") -> dict:
        payload = {
            "message_id": message_id,
            "agent": agent_name,
            "content": content,
            "message_type": MessageType.MESSAGE_CHUNK.value,
            "event": event,
            "created_time": get_current_time()
        }
        if stream_meta:
            payload.update(dict(stream_meta))
        return payload

    stream_id = None
    if can_write_stream and need_stream_out:
        stream_id = str(uuid.uuid4())
        await session.write_custom_stream(_make_payload(stream_id, StreamEvent.START.value, ""))

    restore_usage_parser = None
    if isinstance(stream_options, dict) and bool(stream_options.get("include_usage")):
        restore_usage_parser = _install_usage_only_chunk_parser(llm)

    try:
        stream_kwargs = {
            "messages": messages,
            "model": model_name,
            "tools": tools,
        }
        if stream_options is not None:
            stream_kwargs["stream_options"] = stream_options

        async for chunk in llm.stream(**stream_kwargs):
            _raise_if_cancelled()
            if full_chunk is None:
                full_chunk = chunk
            else:
                full_chunk += chunk
                if len(full_chunk.content) >= MAX_LLM_RESP_LENGTH:
                    logger.warning(
                        f"[llm_astream] llm response is too long, truncate to {MAX_LLM_RESP_LENGTH} characters")
                    full_chunk.content = full_chunk.content[:MAX_LLM_RESP_LENGTH]
                    break
            chunk_content = getattr(chunk, "content", "")
            if can_write_stream and need_stream_out and chunk_content:
                await session.write_custom_stream(_make_payload(stream_id, StreamEvent.MESSAGE.value, chunk_content))
    except Exception as e:
        if can_write_stream and need_stream_out:
            await session.write_custom_stream(_make_payload(stream_id, StreamEvent.DONE.value, ""))
        raise e
    finally:
        if callable(restore_usage_parser):
            restore_usage_parser()

    if can_write_stream and need_stream_out:
        await session.write_custom_stream(_make_payload(stream_id, StreamEvent.DONE.value, ""))

    if full_chunk is None:
        logger.error(f"[llm_astream] llm response is None")
        raise CustomValueException(
            error_code=StatusCode.LLM_RESPONSE_NONE.code,
            message=StatusCode.LLM_RESPONSE_NONE.errmsg)
    return full_chunk


async def ainvoke_llm_with_stats(*args, **kwargs):
    """调用 LLM 并按配置记录调用统计。

    Args:
        llm (dict): LLM 配置字典，包含 model 与 model_name。
        messages (list): 输入消息列表。
        llm_type (str): LLM 类型标识，默认 "basic"。
        agent_name (str): 调用节点或方法名。
        schema (BaseModel | None): 结构化输出模型；为空时返回统一 dict。
        tools (Any): 本次调用绑定工具。
        need_stream_out (bool): 是否将模型输出写入会话流。
        stream_meta (dict | None): 附加流事件字段。
    Returns:
        dict | BaseModel: schema 不为空时返回 schema 实例，否则返回统一后的 dict。
    """
    invoke_args = _parse_invoke_llm_args(args, kwargs)
    llm = invoke_args["llm"]
    messages = invoke_args["messages"]
    llm_type = invoke_args["llm_type"]
    agent_name = invoke_args["agent_name"]
    schema = invoke_args["schema"]
    tools = invoke_args["tools"]
    need_stream_out = invoke_args["need_stream_out"]
    stream_meta = invoke_args["stream_meta"]

    _raise_if_cancelled()
    if not llm:
        raise CustomValueException(
            error_code=StatusCode.LLM_INSTANCE_NONE_ERROR.code,
            message=StatusCode.LLM_INSTANCE_NONE_ERROR.errmsg)
    stats_info_llm = _is_llm_stats_enabled()
    session_id = session_id_ctx.get()
    current_session = None
    if stats_info_llm:
        try:
            current_session = session_context.get()
        except Exception:
            current_session = None
        _ensure_workflow_llm_usage_initialized(session_id=session_id, session=current_session)

    # get model_name
    if not llm_type.strip():
        raise CustomValueException(
            error_code=StatusCode.PARAM_CHECK_ERROR_COMMON_INVALID.code,
            message=StatusCode.PARAM_CHECK_ERROR_COMMON_INVALID.errmsg.format(param="llm_type"))

    model_name = llm.get("model_name", "")
    if not model_name:
        raise CustomValueException(
            error_code=StatusCode.PARAM_CHECK_ERROR_COMMON_INVALID.code,
            message=StatusCode.PARAM_CHECK_ERROR_COMMON_INVALID.errmsg.format(param="model_name"))

    start = None
    if stats_info_llm:
        start = time.time()

    # 真正调用llm处
    messages = transfer_to_jiuwen_messages(messages)
    llm_model = llm.get("model", None)
    if llm_model is None:
        raise CustomValueException(
            error_code=StatusCode.LLM_INSTANCE_NONE_ERROR.code,
            message=StatusCode.LLM_INSTANCE_NONE_ERROR.errmsg)

    resolved_stream_options = (
        _resolve_stream_options(llm_model=llm_model, need_include_usage=True)
        if stats_info_llm
        else None
    )
    response = await llm_astream(
        llm=llm_model,
        messages=messages,
        model_name=model_name,
        agent_name=agent_name,
        tools=tools,
        need_stream_out=need_stream_out,
        stream_meta=stream_meta,
        stream_options=resolved_stream_options,
    )

    if stats_info_llm:
        duration = time.time() - start

        # get usage token usage info
        input_tokens, output_tokens, total_tokens = _extract_usage_tokens(response.usage_metadata)

        llm_stat = {
            "method_name": agent_name,
            "duration": duration,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens
        }
        add_workflow_llm_usage(
            session_id=session_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            agent_name=agent_name,
        )
        metrics_logger.info(
            f"{TIME_LOGGER_TAG} session_id: {session_id_ctx.get()} ------ [LLM CALL STATISTICS]: {llm_stat}"
        )

    response.content = _extract_json(response.content)
    if schema is not None:
        response = schema.model_validate_json(response.content)
        return response
    return _unify_responnse(response)


def _parse_invoke_llm_args(args, kwargs) -> dict:
    return {
        "llm": kwargs.get("llm", args[0] if len(args) > 0 else None),
        "messages": kwargs.get("messages", args[1] if len(args) > 1 else None),
        "llm_type": kwargs.get("llm_type", "basic"),
        "agent_name": kwargs.get("agent_name", "AI"),
        "schema": kwargs.get("schema", None),
        "tools": kwargs.get("tools", None),
        "need_stream_out": kwargs.get("need_stream_out", False),
        "stream_meta": kwargs.get("stream_meta", None),
    }


def _unify_responnse(response):
    temp_response = response.model_dump()
    new_response = copy.deepcopy(temp_response)
    if temp_response.get("tool_calls"):
        tool_calls = temp_response.get("tool_calls")
        for idx, tool_call in enumerate(tool_calls):
            func = tool_call.get("function")
            if not tool_call.get("args") and func and func.get("arguments"):
                arguments = normalize_json_output(func.get("arguments"))
                new_response.get("tool_calls")[idx]["args"] = json.loads(arguments)
            if func and func.get("name"):
                new_response.get("tool_calls")[idx]["name"] = func.get("name")
            if tool_call.get("type"):
                new_response.get("tool_calls")[idx]["type"] = "function"
            new_response.get("tool_calls")[idx].pop("index", None)
    return new_response


def transfer_to_jiuwen_messages(origin_messages: list):
    """转换消息类型"""
    output_messages = []
    for message in origin_messages:
        if isinstance(message, dict):
            role = message.get("role", "")
            content = message.get("content", "")
            name = message.get("name", "")
            if role == "system":
                output_messages.append(SystemMessage(content=content, name=name))
            elif role == "user":
                output_messages.append(UserMessage(content=content, name=name))
            elif role == "assistant":
                output_messages.append(
                    AssistantMessage(
                        content=content,
                        name=name,
                        tool_calls=message.get("tool_calls", []),
                        usage_metadata=message.get("usage_metadata", None),
                        reasoning_content=message.get("reason_content", "")
                    )
                )
            elif role == "tool":
                output_messages.append(
                    ToolMessage(content=content, name=name,
                                tool_call_id=message.get("tool_call_id", "") or f"call_{str(uuid.uuid4().hex[:22])}")
                )
            else:
                logger.error(f"role:{role} not support")
        elif isinstance(message, BaseModel):
            output_messages.append(message)
        else:
            logger.error(f"message type:{type(message)} not support")

    # 部分模型不支持仅传入 system message，缺少 user message 时补一个低语义占位消息兜底。
    if not any(isinstance(message, UserMessage) for message in output_messages):
        output_messages.append(UserMessage(content="."))

    return output_messages


def record_llm_retry_log(*args, **kwargs):
    """Record the retry log of LLM."""
    current_try = kwargs.get("current_try", args[0] if len(args) > 0 else 0)
    max_retries = kwargs.get("max_retries", args[1] if len(args) > 1 else 3)
    section_idx = kwargs.get("section_idx", args[2] if len(args) > 2 else None)
    step_title = kwargs.get("step_title", args[3] if len(args) > 3 else None)
    operation = kwargs.get("operation", args[4] if len(args) > 4 else None)
    error = kwargs.get("error", args[5] if len(args) > 5 else None)
    extra_info = kwargs.get("extra_info", args[6] if len(args) > 6 else None)
    if LogManager.is_sensitive():
        if current_try < max_retries:
            msg = (f"section_idx: {section_idx} | "
                   f"Error when {operation} | "
                   f"retry , number of retries: {current_try} / {max_retries}")
            logger.warning(f"{msg}")
        else:
            msg = (f"section_idx: {section_idx} | "
                   f"Error when {operation} | "
                   f"Failed to {operation}, the max retries have been reached, max retry : {max_retries}")
            logger.error(f"{msg}")
    else:
        error_detail = f"{error}" if error else ""

        if current_try < max_retries:
            msg = (f"section_idx: {section_idx} | step title: {step_title} | "
                   f"Error when {operation}: {error_detail} | "
                   f"Extra Info: {extra_info} | "
                   f"retry , number of retries: {current_try} / {max_retries}")
            logger.warning(msg, exc_info=error is not None)
        else:
            msg = (f"section_idx: {section_idx} | step title: {step_title} | "
                   f"Error when {operation}: {error_detail} | "
                   f"Extra Info: {extra_info} | "
                   f"Failed to {operation}, the max retries have been reached, max retry : {max_retries}")
            logger.error(msg, exc_info=error is not None)
