# -*- coding: UTF-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2025. All rights reserved.
import logging
import json
from typing import List, Dict, NamedTuple, Optional
import base64

from openjiuwen_deepsearch.utils.constants_utils.session_contextvars import llm_context
from openjiuwen_deepsearch.algorithm.prompts.template import apply_system_prompt
from openjiuwen_deepsearch.utils.common_utils.llm_utils import ainvoke_llm_with_stats, normalize_json_output
from openjiuwen_deepsearch.common.exception import CustomValueException
from openjiuwen_deepsearch.common.status_code import StatusCode
from openjiuwen_deepsearch.utils.log_utils.log_manager import LogManager
from openjiuwen_deepsearch.utils.constants_utils.node_constants import NodeId

logger = logging.getLogger(__name__)
MAX_LLM_RETRY_TIMES = 3


def type_check(result, expected_type):
    if not isinstance(result, expected_type):
        error_msg = f"[CHART GENERATION]: 生成结果类型错误, 生成结果类型{type(result)}, 期望类型为{expected_type}"
        raise CustomValueException(StatusCode.CHART_PLACEHOLDER_ERROR.code,
                                    StatusCode.CHART_PLACEHOLDER_ERROR.errmsg.
                                    format(e=error_msg))


def is_equal_length(result, target):
    type_check(result, list)
    if len(result) != target:
        error_msg = f"[CHART GENERATION]: 生成结果数量错误,"
        error_msg += f"生成结果数量{len(result)}, 目标数量{target}"
        raise CustomValueException(StatusCode.CHART_PLACEHOLDER_ERROR.code,
                                    StatusCode.CHART_PLACEHOLDER_ERROR.errmsg.
                                    format(e=error_msg))


async def call_model(model_name: str, prompt: str, user_input: dict, 
                     detection_func_and_args: dict = None, 
                     agent_name: str = NodeId.VLM_CHART_GENERATOR.value):
    """调用LLM模型处理请求
    调用指定的LLM模型处理用户提示，并返回标准化的JSON格式输出
    Args:
        model_name: llm调用名称
        prompt: prompt文件名
        user_input: 需要处理的输入数据
        detection_func_and_args: 输出检测函数和参数
    Returns:
        str: 标准化的JSON格式输出字符串
    """
    retries = 0
    while retries < MAX_LLM_RETRY_TIMES:
        try:
            user_prompt = apply_system_prompt(prompt, user_input)
            llm = llm_context.get().get(model_name)
            response = await ainvoke_llm_with_stats(llm, user_prompt, agent_name=agent_name)
            content = response.get("content", "")
            
            if not detection_func_and_args or detection_func_and_args.get("option", "") != "skip normalize":
                content = normalize_json_output(content)
                content = json.loads(content.replace("```json", "").replace("```", ""))
            if detection_func_and_args and detection_func_and_args.get("detection_func", None):
                # 需要对输出进行检验
                detection_func = detection_func_and_args.get("detection_func")
                params = detection_func_and_args.get("args", {})
                detection_func(content, params)
            return content
        except CustomValueException as e:
            retries += 1
            logger.warning(f'[CHART GENERATION] retry: {retries}/{MAX_LLM_RETRY_TIMES}, '
                               f'call_model error {e}')
        except Exception as e:
            retries += 1
            if LogManager.is_sensitive():
                logger.warning(f'[CHART GENERATION] retry: {retries}/{MAX_LLM_RETRY_TIMES}, '
                               f'call_model error')
            else:
                logger.warning(f'[CHART GENERATION] retry: {retries}/{MAX_LLM_RETRY_TIMES}, '
                               f'call_model error {e}')
    
    logger.error(f'[CHART GENERATION] retry {MAX_LLM_RETRY_TIMES} times, call_model error')
    return []


def get_chart_base64(chart_path: str) -> Optional[str]:
    """
    获取图表的base64编码

    Args:
        chart_path: 图表路径

    Returns:
        Optional[str]: base64编码
    """
    try:
        with open(chart_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")
    except Exception as e:
        logger.error(f"Error reading chart: {e}")
        return None