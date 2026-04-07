# -*- coding: UTF-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2025. All rights reserved.

import logging

from openjiuwen_deepsearch.algorithm.user_feedback_processor.action_definitions import SYNONYM_REWRITE_ACTIONS
from openjiuwen_deepsearch.algorithm.user_feedback_processor.report_edit_utils import (
    adjust_offsets_for_position_changes,
    remove_citations_from_messages,
    remap_inference_ids,
    strip_markup_in_range,
    update_citation_offsets,
)
from openjiuwen_deepsearch.algorithm.prompts.template import apply_system_prompt
from openjiuwen_deepsearch.common.exception import CustomException, CustomValueException
from openjiuwen_deepsearch.common.status_code import StatusCode
from openjiuwen_deepsearch.utils.common_utils.llm_utils import ainvoke_llm_with_stats
from openjiuwen_deepsearch.utils.constants_utils.node_constants import NodeId
from openjiuwen_deepsearch.utils.constants_utils.session_contextvars import llm_context
from openjiuwen_deepsearch.utils.log_utils.log_manager import LogManager

logger = logging.getLogger(__name__)

ACTION_TO_PROMPT = {
    "expand": "synonym_rewrite_expand",
    "polish": "synonym_rewrite_polish",
    "shorten": "synonym_rewrite_shorten",
}


def get_llm_instance(llm_model_name: str):
    """从当前上下文中获取指定名称的 LLM 实例。"""
    all_llms = llm_context.get()
    return all_llms.get(llm_model_name)


class SynonymRewriter:
    """执行报告级别的同义改写，并同步维护引用元数据。"""

    def __init__(self, llm_model_name: str):
        self.llm_model_name = llm_model_name

    @staticmethod
    def get_prompt_name(action: str) -> str:
        """将前端动作名映射为对应的提示模板名称。"""
        if action not in ACTION_TO_PROMPT:
            raise CustomValueException(
                StatusCode.USER_FEEDBACK_PROCESSOR_INVALID_ACTION.code,
                StatusCode.USER_FEEDBACK_PROCESSOR_INVALID_ACTION.errmsg.format(action=action),
            )
        return ACTION_TO_PROMPT[action]

    async def _generate_synonym_rewrite_text(
        self,
        action: str,
        original_text: str,
        language: str,
        user_instruction: str = "",
    ) -> str:
        """调用 LLM 执行一次改写。

        入参 `original_text` 应为已经剥离引用标记的纯文本，
        这样可以避免模型改写 `[[n]](url)` 之类的结构化内容。
        """
        try:
            prompt_name = self.get_prompt_name(action)
            context_vars = {
                "original_text": original_text,
                "language": language,
                "user_instruction": user_instruction,
            }
            messages = apply_system_prompt(prompt_name, context_vars)

            llm = get_llm_instance(self.llm_model_name)

            response = await ainvoke_llm_with_stats(
                llm=llm,
                messages=messages,
                agent_name=NodeId.USER_FEEDBACK_PROCESSOR.value + "_synonym_rewriter",
            )
        except CustomException:
            raise
        except Exception as error:
            raise CustomValueException(
                StatusCode.USER_FEEDBACK_PROCESSOR_REWRITE_ERROR.code,
                StatusCode.USER_FEEDBACK_PROCESSOR_REWRITE_ERROR.errmsg.format(e=str(error)),
            ) from error
        rewritten_text = response.get("content", "") if isinstance(response, dict) else str(response)

        logger.info(f"[SynonymRewriter] action={action}, original_len={len(original_text)}, "
                    f"rewritten_len={len(rewritten_text)}")
        if not LogManager.is_sensitive():
            logger.info(f"[SynonymRewriter] action={action}, original_text={original_text}, "
                        f"rewritten_text={rewritten_text}")
        return rewritten_text

    async def synonym_rewrite(
        self,
        feedback: dict,
        report_content: str,
        citation_messages: dict,
        language: str,
        infer_messages: list | None = None,
    ) -> dict:
        """执行报告级别的同义改写。"""
        action = feedback["action"]
        start_offset = feedback["start_offset"]
        end_offset = feedback["end_offset"]
        user_instruction = feedback.get("user_instruction", "")
        original_selected_len = end_offset - start_offset

        stripped_text, removed_citation_ranges, removed_inference_ids = self._strip_citations_in_range(
            report_content, start_offset, end_offset)

        removed_citation_len = len(report_content) - len(stripped_text)
        stripped_end = end_offset - removed_citation_len
        original_text_clean = stripped_text[start_offset:stripped_end]

        rewritten_text = await self._generate_synonym_rewrite_text(
            action=action,
            original_text=original_text_clean,
            language=language,
            user_instruction=user_instruction,
        )

        new_report = stripped_text[:start_offset] + rewritten_text + stripped_text[stripped_end:]
        rewritten_end_offset = start_offset + len(rewritten_text)

        updated_citation_messages = self._remove_citations_from_messages(
            dict(citation_messages), removed_citation_ranges)

        if "data" in updated_citation_messages:
            updated_citation_messages["data"] = self._update_citation_offsets(
                updated_citation_messages["data"],
                original_end_offset=end_offset,
                original_selected_len=original_selected_len,
                rewritten_len=len(rewritten_text),
            )

        removed_ids_set = set(removed_inference_ids)
        id_remap: dict[int, int] = {}
        updated_infer_messages = []
        for item in (infer_messages or []):
            old_id = item.get("id")
            if old_id not in removed_ids_set:
                new_infer_id = len(updated_infer_messages)
                updated_item = dict(item)
                updated_item["id"] = new_infer_id
                if old_id != new_infer_id:
                    id_remap[old_id] = new_infer_id
                updated_infer_messages.append(updated_item)

        if id_remap:
            new_report, inference_position_changes = self._remap_inference_ids(new_report, id_remap)
            if inference_position_changes and "data" in updated_citation_messages:
                updated_citation_messages["data"] = self._adjust_offsets_for_position_changes(
                    updated_citation_messages["data"], inference_position_changes)

        return dict(
            new_report=new_report,
            original_text=feedback["selected_text"],
            original_start_offset=start_offset,
            original_end_offset=end_offset,
            original_text_clean=original_text_clean,
            rewritten_text=rewritten_text,
            rewritten_start_offset=start_offset,
            rewritten_end_offset=rewritten_end_offset,
            updated_citation_messages=updated_citation_messages,
            updated_infer_messages=updated_infer_messages,
        )

    @staticmethod
    def _strip_citations_in_range(
        text: str, start: int, end: int
    ) -> tuple[str, set[tuple[int, int]], list[int]]:
        """语义同 ``report_edit_utils.strip_markup_in_range``，供改写前得到纯文本选区。"""
        return strip_markup_in_range(text, start, end)

    @staticmethod
    def _remap_inference_ids(
        text: str, id_remap: dict[int, int]
    ) -> tuple[str, list[tuple[int, int]]]:
        """将文本中的推理锚点 ID 按映射表替换，同时返回各替换位置的长度变化。"""
        return remap_inference_ids(text, id_remap)

    @staticmethod
    def _adjust_offsets_for_position_changes(
        citation_data: list, position_changes: list[tuple[int, int]]
    ) -> list:
        """根据文本替换产生的位置变化修正引用偏移量。"""
        return adjust_offsets_for_position_changes(citation_data, position_changes)

    @staticmethod
    def _remove_citations_from_messages(
        citation_messages: dict, removed_citation_ranges: set[tuple[int, int]],
    ) -> dict:
        return remove_citations_from_messages(citation_messages, removed_citation_ranges)

    @staticmethod
    def _update_citation_offsets(
        datas: list, original_end_offset: int, original_selected_len: int, rewritten_len: int
    ) -> list:
        return update_citation_offsets(datas, original_end_offset, original_selected_len, rewritten_len)
