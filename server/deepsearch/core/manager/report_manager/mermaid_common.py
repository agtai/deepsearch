# -*- coding: UTF-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2025-2025. All rights reserved.
"""Common helpers shared by Mermaid offline converters."""

from __future__ import annotations

import logging
import re
from copy import deepcopy
from pathlib import Path


logger = logging.getLogger(__name__)

DEFAULT_CONFIG = {
    "theme": "base",
    "look": "classic",
    "themeVariables": {
        "background": "#ffffff",
        "primaryTextColor": "#111827",
        "secondaryTextColor": "#111827",
        "tertiaryTextColor": "#111827",
        "lineColor": "#374151",
        "textColor": "#111827",
        "mainBkg": "#ffffff",
        "secondBkg": "#f9fafb",
        "tertiaryColor": "#ffffff",
        "xyChart": {
            "plotColorPalette": "#4338ca, #b91c1c, #047857, #b45309, #6d28d9",
        },
    },
}
FRONTMATTER_RE = re.compile(r"^\s*---\s*\n(.*?)\n---\s*\n?", re.DOTALL)


try:
    import yaml

    YAML_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency branch
    YAML_AVAILABLE = False


def _deep_merge(base: dict, override: dict) -> dict:
    """Merge nested dictionaries recursively.

    Args:
        base: 基础配置字典。
        override: 需要覆盖的配置字典。

    Returns:
        dict: 合并后的配置字典。
    """
    result = deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def _extract_frontmatter(code: str) -> tuple[str, str]:
    """Split Mermaid source into frontmatter and body.

    Args:
        code: 原始 Mermaid 源码。

    Returns:
        tuple[str, str]: frontmatter 文本与主体文本。
    """
    match = FRONTMATTER_RE.match(code.strip())
    if match:
        return match.group(1), code.strip()[match.end():].strip()
    return "", code.strip()


def _dump_frontmatter(config_dict: dict) -> str:
    """Serialize Mermaid config into frontmatter text.

    Args:
        config_dict: Mermaid 配置字典。

    Returns:
        str: YAML frontmatter 文本。
    """
    if YAML_AVAILABLE:
        text = yaml.safe_dump(
            {"config": config_dict},
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
        ).strip()
        return f"---\n{text}\n---\n"

    theme_variables = config_dict.get("themeVariables", {})
    xychart = theme_variables.get("xyChart", {})
    return (
        "---\n"
        "config:\n"
        f"  theme: {config_dict.get('theme', 'base')}\n"
        f"  look: {config_dict.get('look', 'classic')}\n"
        "  themeVariables:\n"
        f"    background: '{theme_variables.get('background', '#ffffff')}'\n"
        f"    primaryTextColor: '{theme_variables.get('primaryTextColor', '#111827')}'\n"
        f"    secondaryTextColor: '{theme_variables.get('secondaryTextColor', '#111827')}'\n"
        f"    tertiaryTextColor: '{theme_variables.get('tertiaryTextColor', '#111827')}'\n"
        f"    lineColor: '{theme_variables.get('lineColor', '#374151')}'\n"
        f"    textColor: '{theme_variables.get('textColor', '#111827')}'\n"
        f"    mainBkg: '{theme_variables.get('mainBkg', '#ffffff')}'\n"
        f"    secondBkg: '{theme_variables.get('secondBkg', '#f9fafb')}'\n"
        f"    tertiaryColor: '{theme_variables.get('tertiaryColor', '#ffffff')}'\n"
        "    xyChart:\n"
        f"      plotColorPalette: '{xychart.get('plotColorPalette', '#4338ca, #b91c1c, #047857, #b45309, #6d28d9')}'\n"
        "---\n"
    )


def clean_mermaid_code(code: str) -> str:
    """Normalize Mermaid code and ensure default frontmatter exists.

    Args:
        code: 原始 Mermaid 源码。

    Returns:
        str: 清理后的 Mermaid 源码。
    """
    frontmatter, body = _extract_frontmatter(code.strip())
    if not frontmatter:
        return (_dump_frontmatter(DEFAULT_CONFIG) + body.strip()).strip()

    if not YAML_AVAILABLE:
        logger.warning("PyYAML is unavailable; keeping existing Mermaid frontmatter.")
        return f"---\n{frontmatter.strip()}\n---\n{body.strip()}"

    try:
        parsed = yaml.safe_load(frontmatter) or {}
        if "config" in parsed and isinstance(parsed["config"], dict):
            config = _deep_merge(DEFAULT_CONFIG, parsed["config"])
        else:
            config = _deep_merge(DEFAULT_CONFIG, parsed if isinstance(parsed, dict) else {})
    except Exception as exc:
        logger.warning("Failed to parse Mermaid frontmatter, using defaults: %s", exc)
        config = DEFAULT_CONFIG

    return (_dump_frontmatter(config) + body.strip()).strip()


def save_failed_mermaid_source(code: str, debug_base_path: Path, *, extra_text: str = "") -> None:
    """Persist Mermaid source and optional diagnostics for debugging.

    Args:
        code: Mermaid 源码。
        debug_base_path: 调试输出基础路径。
        extra_text: 额外错误信息。

    Returns:
        None.
    """
    debug_base_path.parent.mkdir(parents=True, exist_ok=True)
    debug_base_path.with_suffix(".mmd").write_text(code, encoding="utf-8")
    if extra_text:
        debug_base_path.with_suffix(".error.txt").write_text(extra_text, encoding="utf-8")


def load_svg_markup(svg_path: str | Path) -> str:
    """Load SVG markup and strip XML/doctype preamble.

    Args:
        svg_path: SVG 文件路径。

    Returns:
        str: 适合嵌入 HTML 的 SVG 文本。
    """
    svg_text = Path(svg_path).read_text(encoding="utf-8")
    svg_text = re.sub(r"^\s*<\?xml[^>]*>\s*", "", svg_text, flags=re.IGNORECASE)
    svg_text = re.sub(r"^\s*<!DOCTYPE[^>]*>\s*", "", svg_text, flags=re.IGNORECASE)
    return svg_text.strip()
