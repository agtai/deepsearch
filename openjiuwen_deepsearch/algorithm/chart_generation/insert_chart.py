# -*- coding: UTF-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2025. All rights reserved.
"""
图表插入报告模块

功能：
1. 将图表插入报告
2. 在图表下加入图表描述，并加上引用标签
"""

import logging
from typing import Dict, List, Any, Tuple
import re
import copy
import html

from openjiuwen_deepsearch.common.exception import CustomValueException
from openjiuwen_deepsearch.common.status_code import StatusCode

logger = logging.getLogger(__name__)


# 安全相关的URL scheme白名单
SAFE_URL_SCHEMES = frozenset(['http', 'https'])


def escape_html_text(text: str) -> str:
    """
    对文本进行HTML转义，防止HTML/Markdown注入

    Args:
        text: 需要转义的文本

    Returns:
        str: 转义后的安全文本
    """
    if not text:
        return ""
    # 转义HTML特殊字符
    return html.escape(text, quote=True)


def escape_markdown_link_text(text: str) -> str:
    """
    对Markdown链接文本进行转义

    Markdown链接格式: [text](url)
    需要转义的特殊字符: [ ] ( ) \

    Args:
        text: 需要转义的链接文本

    Returns:
        str: 转义后的安全文本
    """
    if not text:
        return ""
    # Markdown链接文本中需要转义的字符
    # 使用反斜杠转义
    escaped = text.replace('\\', '\\\\')
    escaped = escaped.replace('[', '\\[')
    escaped = escaped.replace(']', '\\]')
    escaped = escaped.replace('(', '\\(')
    escaped = escaped.replace(')', '\\)')
    return escaped


def validate_and_sanitize_url(url: str) -> str:
    """
    验证URL并确保只允许安全的scheme (http/https)

    Args:
        url: 待验证的URL

    Returns:
        str: 安全的URL，若scheme不合法则返回空字符串
    """
    if not url:
        return ""

    # 解析URL获取scheme
    url_stripped = url.strip()

    # 检查是否以合法scheme开头
    # 格式: scheme://...
    scheme_match = re.match(r'^([a-zA-Z][a-zA-Z0-9+.-]*)://', url_stripped)

    if scheme_match:
        scheme = scheme_match.group(1).lower()
        if scheme not in SAFE_URL_SCHEMES:
            logger.warning(f"URL scheme '{scheme}' is not allowed, URL blocked: {url_stripped[:100]}")
            return ""
        return url_stripped
    else:
        # 没有scheme的相对路径或不完整URL，视为不安全
        logger.warning(f"URL without valid scheme blocked: {url_stripped[:100]}")
        return ""


class InsertChartNode:
    """将图表插入报告"""

    def __init__(self, output_dir: str):
        """
        初始化

        Args:
            source_trace_datas: 溯源数据列表
        """
        self.source_trace_datas = None
        self.report_content = None
        self.output_dir = output_dir
        self._log_prefix = "[InsertChartNode]"
        self._inser_source_tracer_count = 0
        
    def run(
        self, report_content: str, 
        charts_info: Dict[str, List[Dict[str, Any]]],
        source_trace_datas: List[Dict[str, Any]]
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """
        将图表插入报告

        Args:
            report_content: 报告内容
            charts_info: 图表信息字典 {section_index: [chart1, chart2, ...]}
            source_trace_datas: 溯源数据列表

        Returns:
            str: 插入占位符后的报告内容
        """
        try:
            if not charts_info:
                raise ValueError(f"{self._log_prefix} charts_info is empty!")
            self.report_content = report_content
            self.source_trace_datas = copy.deepcopy(source_trace_datas)
            
            modified_report = self.report_content

            for _, charts in charts_info.items():
                for chart in charts:
                    modified_report = self._insert_chart_placeholder(
                        modified_report, chart
                    )
            logger.info(f"{self._log_prefix} The count of source trace " \
                        f"for vlm_charts is {self._inser_source_tracer_count}. " \
                        f"Total count is {len(self.source_trace_datas)}.")
        except Exception as e:
            error_msg = f"Error inserting chart tasks: {repr(e)}"
            logger.error(error_msg)
            raise CustomValueException(StatusCode.CHART_INSERT_ERROR.code,
                                       StatusCode.CHART_INSERT_ERROR.errmsg.format(e=error_msg)) from e

        return modified_report, self.source_trace_datas

    def _insert_chart_placeholder(
        self, report_content: str, chart: Dict[str, Any]
    ) -> str:
        """
        在报告中找到锚点文本并插入图表占位符和描述

        Args:
            report_content: 报告内容
            chart: 图表信息
        Returns:
            str: 修改后的报告内容
        """

        anchor_text = chart.get("anchor_match_para", "")
        chart_title = chart.get("chart_title", "")
        description = chart.get("description", "")
        chart_id = chart.get("chart_id", "")
        source_datas = chart.get("source_datas", [])

        # 对图表标题和描述进行HTML转义，防止HTML/Markdown注入
        safe_chart_title = escape_html_text(chart_title)
        safe_description = escape_html_text(description)

        placeholder = f"(#insertChart:{chart_id})"
        insertion = f"{placeholder}\n<font size=2>**{safe_chart_title}**: {safe_description}</font>"

        # 将新插入的溯源信息插入到source_trace_datas对应位置中
        if self._insert_source_trace_data(report_content, chart):
            # 统计vlm生成图模块共插入了多少条溯源信息
            self._inser_source_tracer_count += len(source_datas)
            # 溯源信息成功插入datas, 在报告中插入溯源信息
            for source_data in source_datas:
                # 对链接文本进行Markdown转义
                safe_link_title = escape_markdown_link_text(source_data.get('title', ''))
                # 验证并清理URL，只允许http/https scheme
                safe_url = validate_and_sanitize_url(source_data.get('url', ''))

                # 如果URL验证失败，使用一个占位链接文本（不插入实际链接）
                if safe_url:
                    insertion += f"[source_tracer_result][{safe_link_title}]({safe_url})"
            logger.debug("%s Inserted source trace data, the figure id is %s",
                        self._log_prefix, chart.get('chart_id', ''))
        else:
            # 溯源信息插入失败，报告的图表不显示其溯源
            logger.warning(f"{self._log_prefix} Failed to insert source trace data, "
                           f"the figure id is {chart.get('chart_id', '')}")

        # 在报告中插入图表占位符、描述和溯源信息
        if anchor_text in report_content:
            modified_content = report_content.replace(
                anchor_text, anchor_text + "\n\n" + insertion, 1
            )
            logger.debug("%s Inserted chart placeholder %s after anchor text",
                        self._log_prefix, placeholder)
            return modified_content
        else:
            logger.warning(f"{self._log_prefix} Anchor text not found in report: {anchor_text[:50]}...")
            return report_content

    def _insert_source_trace_data(
        self, report_content: str,
        chart: Dict[str, Any]) -> bool:
        """
        在报告中找到source_trace_datas对应位置并插入溯源信息

        Args:
            report_content: 报告内容
            source_data: 溯源信息
        """
        try:
            # 溯源信息为空，则不插入溯源信息
            if not self.source_trace_datas:
                return False
            
            anchor_text = chart.get("anchor_match_para", "")
            source_datas = chart.get("source_datas", [])
            
            # 获取anchor_text之前的内容中包含的溯源标识符个数
            source_tracer_pattern = r'\[source_tracer_result\]\[.*?\]\(.*?\)'
            source_tracer_count_before = len(re.findall(source_tracer_pattern, 
                                                        report_content[:report_content.find(anchor_text)]))            
            # 获取anchor_text中的内容中包含的溯源标识符个数
            source_tracer_count_current = len(re.findall(source_tracer_pattern, anchor_text))
            
            # 插入图表溯源信息到source_trace_datas对应位置中
            data_source_insert_pos = source_tracer_count_before + source_tracer_count_current
            
            # 设定句子位置起点
            if data_source_insert_pos > 0:
                sentence_position = self.source_trace_datas[data_source_insert_pos - 1].get("_sentence_position", 0)
            else:
                sentence_position = 0
            
            pos_offset = 0
            insert_source_traces = []
            for source_data in source_datas:
                pos_offset += 1
                chart_source_data = {
                    "name": "",
                    "url": source_data.get("url", ""),
                    "title": source_data.get("title", ""),
                    "content": source_data.get("original_content", ""),
                    "source": "",
                    "publish_time": "",
                    "from": "",
                    "chunk": chart.get("description", ""),
                    "score": chart.get("score", 0) / 100, # 后续分数应用于溯源模块，分制对齐
                    "id": "",
                    "_sentence_position": sentence_position + pos_offset, # 符合datas中位置递增变化即可
                    "is_vlm_chart": True,
                }
                insert_source_traces.append(chart_source_data)
            # 插入点后的所有溯源的_sentence_position偏移
            source_tracer_count = len(self.source_trace_datas)
            if data_source_insert_pos < source_tracer_count:
                for index in range(data_source_insert_pos, source_tracer_count):
                    self.source_trace_datas[index]["_sentence_position"] += pos_offset
                # 将vlm生成的图的溯源插入source_trace_datas
                self.source_trace_datas[data_source_insert_pos:data_source_insert_pos] = insert_source_traces
            else:
                self.source_trace_datas.extend(insert_source_traces)
            return True
        except Exception as e:
            logger.error(f"{self._log_prefix} Failed to insert source trace data: {e}, \
                the figure id is {chart.get('chart_id', '')}")
            return False