from types import SimpleNamespace

import pytest

from server.deepsearch.core.manager.agent import DeepSearchAgentManager
from server.schemas.deepsearch_run import DeepSearchRequest


class _FakeAgentFactory:
    def __init__(self):
        self.created = []

    def create_agent(self, config):
        agent = SimpleNamespace(config=config, research_name="demo")
        self.created.append(agent)
        return agent


class _FakeCheckpointer:
    def __init__(self):
        self.released = []

    async def release(self, session_id):
        self.released.append(session_id)


def _build_request(conversation_id: str) -> DeepSearchRequest:
    """构造用于 AgentManager 测试的最小请求对象。

    Args:
        conversation_id: 当前测试场景使用的会话 ID。

    Returns:
        DeepSearchRequest: 最小可用请求对象。
    """
    return DeepSearchRequest(
        space_id="space-1",
        conversation_id=conversation_id,
        message="hello",
        llm_config={
            "general": {
                "model_name": "mock-model",
                "model_type": "openai",
                "base_url": "https://example.com/v1",
                "api_key": "secret",
            }
        },
        web_search_config={
            "web_search_config_id": 1,
            "max_web_search_results": 5,
        },
        info_collector_search_method="web",
        search_mode="research",
        execution_method="parallel",
    )


@pytest.mark.asyncio
async def test_cleanup_session_cache_evicts_agent_cache(monkeypatch):
    """清理会话时应删除该会话对应的 agent 缓存。

    Args:
        monkeypatch: pytest 运行时打桩工具。

    Returns:
        None.
    """
    factory = _FakeAgentFactory()
    manager = DeepSearchAgentManager(agent_factory=factory)
    fake_checkpointer = _FakeCheckpointer()

    monkeypatch.setattr(
        "server.deepsearch.core.manager.agent.CheckpointerFactory.get_checkpointer",
        lambda: fake_checkpointer,
    )

    request_a = _build_request("conversation-a")
    request_b = _build_request("conversation-b")

    agent_a = manager.get_or_create_agent(request_a, object(), agent_config={"a": 1})
    agent_b = manager.get_or_create_agent(request_b, object(), agent_config={"b": 2})

    assert len(factory.created) == 2

    await manager.cleanup_session_cache(request_a.space_id, request_a.conversation_id)

    # 会话 A 清理后应重新创建，不应复用旧实例。
    recreated_agent_a = manager.get_or_create_agent(request_a, object(), agent_config={"a": 1})

    assert fake_checkpointer.released == ["conversation-a"]
    assert recreated_agent_a is not agent_a
    assert manager.get_or_create_agent(request_b, object(), agent_config={"b": 2}) is agent_b
