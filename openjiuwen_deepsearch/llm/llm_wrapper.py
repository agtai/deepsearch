# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2025. All rights reserved.

import logging
from typing import Optional

from openjiuwen_deepsearch.framework.openjiuwen.llm.llm_model_factory import LLMModelFactory, LLMModelParams
from openjiuwen_deepsearch.config.config import Config, LLMConfig
from openjiuwen_deepsearch.llm.llm_request_adapter import merge_thinking_extension
from openjiuwen_deepsearch.utils.common_utils.security_utils import zero_secret
from openjiuwen_deepsearch.utils.validation_utils.param_validation import validate_llm_obj_params

logger = logging.getLogger(__name__)


def create_llm_obj(llm_config: LLMConfig, thinking_enabled: Optional[bool] = None):
    """创建自定义llm"""
    try:
        validate_llm_obj_params(llm_config)
        # thinking_enabled 是三态语义：None 表示保持原始 extension，不注入思考开关；
        # True/False 表示按厂商规则显式开启/关闭思考模式。
        merged_extension = (
            llm_config.extension
            if thinking_enabled is None
            else merge_thinking_extension(llm_config, thinking_enabled)
        )
        model_params = LLMModelParams(
            model_provider=llm_config.model_type,
            api_key=bytes(llm_config.api_key).decode('utf-8'),
            api_base=llm_config.base_url,
            timeout=Config().service_config.llm_timeout,
            hyper_parameters=llm_config.hyper_parameters,
            extension=merged_extension
        )
        model = LLMModelFactory().get_model(model_params)
        model_name = llm_config.model_name
        return dict(model=model, model_name=model_name)
    finally:
        zero_secret(llm_config.api_key)
