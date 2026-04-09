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
import os

from openjiuwen_deepsearch.common.exception import CustomValueException
from openjiuwen_deepsearch.common.status_code import StatusCode

logger = logging.getLogger(__name__)


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
    
        placeholder = f"(#insertChart:{chart_id})"
        insertion = f"{placeholder}\n<font size=2>**{chart_title}**: {description}</font>"
            
        # 将新插入的溯源信息插入到source_trace_datas对应位置中
        if self._insert_source_trace_data(report_content, chart):
            # 溯源信息成功插入datas, 在报告中插入溯源信息
            for source_data in source_datas:
                insertion += f"[source_tracer_result][{source_data.get('title', '')}]({source_data.get('url', '')})"
            logger.info(f"Inserted source trace data, \
                the figure id is {chart.get('chart_id', '')}")
        else:
            # 溯源信息插入失败，报告的图表不显示其溯源
            logger.warning(f"Failed to insert source trace data, \
                the figure id is {chart.get('chart_id', '')}")

        # 在报告中插入图表占位符、描述和溯源信息
        if anchor_text in report_content:
            modified_content = report_content.replace(
                anchor_text, anchor_text + "\n\n" + insertion
            )
            logger.info(f"Inserted chart placeholder {placeholder} after anchor text")
            return modified_content
        else:
            logger.warning(f"Anchor text not found in report: {anchor_text[:50]}...")
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
            
            pos_offset = 1
            for source_data in source_datas:
                chart_source_data = {
                    "name": "",
                    "url": source_data.get("url", ""),
                    "title": source_data.get("title", ""),
                    "content": source_data.get("original_content", ""),
                    "source": "",
                    "publish_time": "",
                    "from": "",
                    "chunk": chart.get("description", ""),
                    "score": 8.5,
                    "id": "",
                    "_sentence_position": sentence_position + pos_offset, # 符合datas中位置递增变化即可
                    "is_vlm_chart": True,
                }
                pos_offset += 1
                self.source_trace_datas.insert(data_source_insert_pos, chart_source_data)
                data_source_insert_pos += 1
            return True
        except Exception as e:
            logger.error(f"Failed to insert source trace data: {e}, \
                the figure id is {chart.get('chart_id', '')}")
            return False