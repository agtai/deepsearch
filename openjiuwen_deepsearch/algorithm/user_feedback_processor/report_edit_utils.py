# -*- coding: UTF-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2025. All rights reserved.

import re

_CITATION_PATTERN = re.compile(
    r'(?:\[\[\d+\]\]\(.*?\)|\[\s*citation:\s*\d+\s*\])'
)
_INFERENCE_MARKER_PATTERN = re.compile(r'\[([^\]]+)\]\(#inference:(\d+)\)')


def strip_markup_in_range(
    text: str,
    start: int,
    end: int,
) -> tuple[str, set[tuple[int, int]], list[int]]:
    """移除指定范围内的 citation 标记，并将 inference 标记还原为纯文本。

    Args:
        text: 原始报告文本。
        start: 选区起始偏移量。
        end: 选区结束偏移量。

    Returns:
        tuple[str, set[tuple[int, int]], list[int]]:
            - 剥离标记后的文本
            - 被移除的 citation 标记的偏移范围集合
            - 被移除的 inference 标记的 ID 列表
    """
    removed_citation_ranges: set[tuple[int, int]] = set()
    removed_inference_ids: list[int] = []

    all_matches = []
    for match in _CITATION_PATTERN.finditer(text):
        m_start, m_end = match.start(), match.end()
        if m_start >= start and m_end <= end:
            all_matches.append(("citation", match))
    for match in _INFERENCE_MARKER_PATTERN.finditer(text):
        m_start, m_end = match.start(), match.end()
        if m_start >= start and m_end <= end:
            all_matches.append(("inference", match))
    all_matches.sort(key=lambda item: item[1].start())

    parts = []
    last_pos = 0
    for match_type, match in all_matches:
        m_start, m_end = match.start(), match.end()
        parts.append(text[last_pos:m_start])
        if match_type == "citation":
            removed_citation_ranges.add((m_start, m_end))
        else:
            parts.append(match.group(1))
            removed_inference_ids.append(int(match.group(2)))
        last_pos = m_end

    parts.append(text[last_pos:])
    return "".join(parts), removed_citation_ranges, removed_inference_ids


def remove_citations_from_messages(
    citation_messages: dict,
    removed_ranges: set[tuple[int, int]],
) -> dict:
    """删除被当前编辑范围完全覆盖的 citation 条目，并重排 id。"""
    if "data" not in citation_messages:
        return citation_messages

    citation_messages["data"] = [
        item
        for item in citation_messages["data"]
        if (item.get("citation_start_offset"), item.get("citation_end_offset")) not in removed_ranges
    ]
    for new_id, item in enumerate(citation_messages["data"]):
        item["id"] = new_id
    return citation_messages


def update_citation_offsets(
    datas: list,
    original_end_offset: int,
    original_selected_len: int,
    rewritten_len: int,
) -> list:
    """平移编辑区间之后的 citation offset。

    Args:
        datas: 引用数据列表。
        original_end_offset: 原始选区结束偏移量。
        original_selected_len: 原始选区长度。
        rewritten_len: 改写后文本长度。

    Returns:
        list: 更新后的引用数据列表。
    """
    delta = rewritten_len - original_selected_len
    if delta == 0:
        return datas

    for data in datas:
        start = data.get("citation_start_offset")
        end = data.get("citation_end_offset")
        if start is not None and start >= original_end_offset:
            data["citation_start_offset"] = start + delta
            data["citation_end_offset"] = end + delta
    return datas


def remap_inference_ids(
    text: str,
    id_remap: dict[int, int],
) -> tuple[str, list[tuple[int, int]]]:
    """将文本中的 inference 标记 ID 按映射表替换，并返回由替换带来的位置变化。"""
    pieces = []
    position_changes: list[tuple[int, int]] = []
    last_pos = 0

    for match in _INFERENCE_MARKER_PATTERN.finditer(text):
        old_id = int(match.group(2))
        new_id = id_remap.get(old_id, old_id)
        new_full = f"[{match.group(1)}](#inference:{new_id})"
        delta = len(new_full) - len(match.group(0))
        pieces.append(text[last_pos:match.start()])
        pieces.append(new_full)
        last_pos = match.end()
        if delta != 0:
            position_changes.append((match.start(), delta))

    pieces.append(text[last_pos:])
    return "".join(pieces), position_changes


def adjust_offsets_for_position_changes(
    citation_data: list,
    position_changes: list[tuple[int, int]],
) -> list:
    """根据 inference 标记替换带来的长度变化修正后续 citation 的偏移量。"""
    for item in citation_data:
        cit_start = item.get("citation_start_offset")
        if cit_start is None:
            continue
        adjustment = sum(delta for pos, delta in position_changes if pos < cit_start)
        if adjustment:
            item["citation_start_offset"] = cit_start + adjustment
            item["citation_end_offset"] = item.get("citation_end_offset", 0) + adjustment
    return citation_data
