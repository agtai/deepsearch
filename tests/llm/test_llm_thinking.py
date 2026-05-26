# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2025. All rights reserved.

import logging

import pytest

from openjiuwen_deepsearch.config.config import LLMConfig
from openjiuwen_deepsearch.llm import llm_wrapper
from openjiuwen_deepsearch.llm import llm_request_adapter
from openjiuwen_deepsearch.llm.llm_request_adapter import (
    merge_thinking_extension,
    resolve_llm_thinking_enabled,
)


def _llm_config(
    *,
    base_url: str,
    model_name: str = "test-model",
    model_type: str = "openai",
    extension: dict | None = None,
) -> LLMConfig:
    return LLMConfig(
        model_name=model_name,
        model_type=model_type,
        base_url=base_url,
        api_key=bytearray(b"test-key"),
        extension=extension or {},
    )


@pytest.mark.parametrize(
    "base_url, model_name",
    [
        ("https://api.deepseek.com", "deepseek-reasoner"),
        ("https://open.bigmodel.cn/api/paas/v4", "glm-4.7"),
        ("https://api.moonshot.cn/v1", "kimi-k2"),
        ("https://ark.cn-beijing.volces.com/api/v3", "doubao-seed"),
        ("https://api.modelarts-maas.com/v1/chat/completion", "huawei-maas-model"),
        ("https://api.modelarts-maas.com/v2/chat/completions", "huawei-maas-model"),
    ],
)
def test_merge_thinking_extension_uses_thinking_type(base_url, model_name):
    config = _llm_config(base_url=base_url, model_name=model_name)

    result = merge_thinking_extension(config, thinking_enabled=False)

    assert result["extra_body"]["thinking"] == {"type": "disabled"}


def test_merge_thinking_extension_uses_dashscope_enable_thinking(caplog):
    config = _llm_config(
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        extension={"extra_body": {"thinking": {"type": "enabled"}, "other": 1}},
    )
    caplog.set_level(logging.WARNING, logger=llm_request_adapter.__name__)

    result = merge_thinking_extension(config, thinking_enabled=False)

    assert result["extra_body"]["enable_thinking"] is False
    assert result["extra_body"]["other"] == 1
    assert "thinking" not in result["extra_body"]
    assert "Existing thinking fields in LLMConfig.extension are overridden" in caplog.text
    assert "extra_body.thinking" in caplog.text


def test_merge_thinking_extension_uses_siliconflow_top_level_field():
    config = _llm_config(
        base_url="https://api.siliconflow.cn/v1",
        model_type="siliconflow",
        extension={"extra_body": {"enable_thinking": True}},
    )

    result = merge_thinking_extension(config, thinking_enabled=False)

    assert result["enable_thinking"] is False
    assert "extra_body" in result
    assert "enable_thinking" not in result["extra_body"]


def test_merge_thinking_extension_uses_huawei_openai_compatible_chat_template_kwargs():
    config = _llm_config(
        base_url="https://api.modelarts-maas.com/openai/v1",
    )

    result = merge_thinking_extension(config, thinking_enabled=False)

    assert result["extra_body"]["chat_template_kwargs"] == {"enable_thinking": False}
    assert "thinking" not in result["extra_body"]


def test_merge_thinking_extension_keeps_original_extension_unchanged():
    original_extension = {"extra_body": {"thinking": {"type": "enabled"}}}
    config = _llm_config(base_url="https://api.deepseek.com", extension=original_extension)

    result = merge_thinking_extension(config, thinking_enabled=False)

    assert result["extra_body"]["thinking"] == {"type": "disabled"}
    assert original_extension == {"extra_body": {"thinking": {"type": "enabled"}}}


def test_merge_thinking_extension_warns_and_keeps_minimax_extension(caplog):
    extension = {"extra_body": {"enable_thinking": True}}
    config = _llm_config(base_url="https://api.minimax.io/v1", extension=extension)
    caplog.set_level(logging.WARNING, logger=llm_request_adapter.__name__)

    result = merge_thinking_extension(config, thinking_enabled=False)

    assert result == extension
    assert "does not support thinking switch" in caplog.text
    assert "minimax" in caplog.text


def test_resolve_llm_thinking_enabled_accepts_runtime_service_config():
    assert resolve_llm_thinking_enabled({"llm_thinking_enabled": "true"}) is True
    assert resolve_llm_thinking_enabled({"llm_thinking_enabled": "false"}) is False


def test_create_llm_obj_passes_merged_extension_to_factory(monkeypatch):
    captured = {}

    class DummyFactory:
        def get_model(self, params):
            captured["params"] = params
            return object()

    monkeypatch.setattr(llm_wrapper, "LLMModelFactory", lambda: DummyFactory())
    config = _llm_config(
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model_name="qwen-plus",
    )

    result = llm_wrapper.create_llm_obj(config, thinking_enabled=False)

    assert result["model_name"] == "qwen-plus"
    assert captured["params"].extension["extra_body"]["enable_thinking"] is False


def test_create_llm_obj_skips_thinking_switch_by_default(monkeypatch):
    captured = {}

    class DummyFactory:
        def get_model(self, params):
            captured["params"] = params
            return object()

    monkeypatch.setattr(llm_wrapper, "LLMModelFactory", lambda: DummyFactory())
    config = _llm_config(
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model_name="qwen-plus",
        extension={"extra_body": {"original": True}},
    )

    llm_wrapper.create_llm_obj(config)

    assert captured["params"].extension == {"extra_body": {"original": True}}
