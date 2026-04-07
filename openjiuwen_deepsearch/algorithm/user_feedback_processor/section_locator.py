# -*- coding: UTF-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2025. All rights reserved.

import re
from dataclasses import dataclass

_HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)


@dataclass(frozen=True)
class LocatedSection:
    """报告内由 Markdown 标题划定的一块连续区间及其元数据。"""

    section_start_offset: int
    section_end_offset: int
    section_text: str
    section_heading: str


def locate_section(report: str, start_offset: int, end_offset: int) -> LocatedSection:
    """定位包含 ``[start_offset, end_offset)`` 的最小标题区块；无标题时退回整篇报告。"""
    headings = [
        {
            "start": match.start(),
            "end": match.end(),
            "level": len(match.group(1)),
            "heading": match.group(0),
        }
        for match in _HEADING_PATTERN.finditer(report)
    ]
    if headings:
        return _locate_smallest_enclosing_heading_block(report, start_offset, end_offset, headings)
    return LocatedSection(
        section_start_offset=0,
        section_end_offset=len(report),
        section_text=report,
        section_heading="",
    )


def _locate_smallest_enclosing_heading_block(
    report: str,
    start_offset: int,
    end_offset: int,
    headings: list[dict],
) -> LocatedSection:
    """在已解析的 ``headings`` 列表上选取能包住选区、span 最小且标题层级尽量深的一块。

    Args:
        report: 报告正文。
        start_offset: 选区起始偏移量。
        end_offset: 选区结束偏移量。
        headings: 已解析的标题列表，每个元素包含 start、end、level、heading 字段。

    Returns:
        LocatedSection: 最小包围标题区块信息；无匹配时返回整篇报告。
    """
    candidates = []
    for index, heading in enumerate(headings):
        block_start = heading["start"]
        block_end = len(report)
        for next_heading in headings[index + 1:]:
            if next_heading["level"] <= heading["level"]:
                block_end = next_heading["start"]
                break
        if start_offset >= block_start and end_offset <= block_end:
            candidates.append(
                {
                    "start": block_start,
                    "end": block_end,
                    "heading": heading["heading"],
                    "span": block_end - block_start,
                    "level": heading["level"],
                }
            )

    if not candidates:
        return LocatedSection(
            section_start_offset=0,
            section_end_offset=len(report),
            section_text=report,
            section_heading="",
        )

    best = min(candidates, key=lambda item: (item["span"], -item["level"], -item["start"]))
    return LocatedSection(
        section_start_offset=best["start"],
        section_end_offset=best["end"],
        section_text=report[best["start"]:best["end"]],
        section_heading=best["heading"],
    )
