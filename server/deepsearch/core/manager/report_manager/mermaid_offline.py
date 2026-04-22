# -*- coding: UTF-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2025-2025. All rights reserved.
"""Render Mermaid diagrams offline through Mermaid CLI."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

from server.deepsearch.core.manager.report_manager.mermaid_common import (
    clean_mermaid_code,
    save_failed_mermaid_source,
)


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class MermaidCliStatus:
    """Describe Mermaid CLI discovery results.

    Attributes:
        path (str | None): 可执行文件路径。
        checked_paths (tuple[str, ...]): 已检查过的候选路径。
        message (str): 结果说明。
    """

    path: str | None
    checked_paths: tuple[str, ...]
    message: str

    @property
    def available(self) -> bool:
        """Return whether a Mermaid CLI executable was found.

        Returns:
            bool: 是否找到可用的 Mermaid CLI。
        """
        return self.path is not None


def resolve_mmdc_path() -> str | None:
    """Resolve Mermaid CLI path from environment and PATH lookups.

    Returns:
        str | None: 找到时返回可执行文件路径，否则返回 `None`。
    """
    candidates: list[str] = []
    checked: set[str] = set()

    env_path = os.getenv("MERMAID_MMDC_PATH")
    if env_path:
        candidates.append(env_path)

    for name in ("mmdc.cmd", "mmdc", "mmdc.ps1"):
        resolved = shutil.which(name)
        if resolved:
            candidates.append(resolved)

    appdata = os.getenv("APPDATA")
    if appdata:
        candidates.extend(
            [
                str(Path(appdata) / "npm" / "mmdc.cmd"),
                str(Path(appdata) / "npm" / "mmdc"),
            ]
        )

    home = Path.home()
    candidates.extend(
        [
            str(home / "AppData" / "Roaming" / "npm" / "mmdc.cmd"),
            str(home / "AppData" / "Roaming" / "npm" / "mmdc"),
            str(Path(r"C:\Program Files\nodejs") / "mmdc.cmd"),
            str(Path(r"C:\Program Files\nodejs") / "mmdc"),
        ]
    )

    for candidate in candidates:
        normalized = str(Path(candidate).expanduser())
        if normalized in checked:
            continue
        checked.add(normalized)
        if Path(normalized).exists():
            return normalized
    return None


def ensure_mermaid_cli() -> MermaidCliStatus:
    """Detect Mermaid CLI and summarize lookup results.

    Returns:
        MermaidCliStatus: Mermaid CLI 检测结果。
    """
    checked_paths: list[str] = []

    env_path = os.getenv("MERMAID_MMDC_PATH")
    if env_path:
        checked_paths.append(str(Path(env_path).expanduser()))

    for name in ("mmdc.cmd", "mmdc", "mmdc.ps1"):
        resolved = shutil.which(name)
        if resolved:
            checked_paths.append(resolved)

    path = resolve_mmdc_path()
    if path:
        return MermaidCliStatus(
            path=path,
            checked_paths=tuple(dict.fromkeys(checked_paths)),
            message=f"Using Mermaid CLI: {path}",
        )

    return MermaidCliStatus(
        path=None,
        checked_paths=tuple(dict.fromkeys(checked_paths)),
        message="Mermaid CLI was not found. Install @mermaid-js/mermaid-cli or set MERMAID_MMDC_PATH.",
    )


def _build_mmdc_command(
    mmdc_path: str,
    input_path: Path,
    output_path: Path,
    output_format: str,
) -> list[str]:
    """Build the Mermaid CLI command line.

    Args:
        mmdc_path: Mermaid CLI 可执行路径。
        input_path: 输入 `.mmd` 文件路径。
        output_path: 输出图片路径。
        output_format: 目标格式，例如 `svg` 或 `png`。

    Returns:
        list[str]: 可直接交给 subprocess 的命令列表。
    """
    args = [
        "-i",
        str(input_path),
        "-o",
        str(output_path),
        "-b",
        "white",
    ]
    if output_format.lower() == "png":
        args.extend(["-s", "2"])

    mmdc_file = Path(mmdc_path)
    if os.name == "nt" and mmdc_file.suffix.lower() in {".cmd", ".bat"}:
        return ["cmd.exe", "/d", "/c", str(mmdc_file), *args]
    return [str(mmdc_file), *args]


def _build_mmdc_failure_details(
    command: list[str],
    result: subprocess.CompletedProcess[str],
) -> str:
    """Build a readable error message for Mermaid CLI failures.

    Args:
        command: 执行过的命令。
        result: subprocess 返回结果。

    Returns:
        str: 汇总后的失败详情文本。
    """
    parts = [
        f"command: {' '.join(command)}",
        f"returncode: {result.returncode}",
    ]
    if result.stdout.strip():
        parts.extend(["stdout:", result.stdout.strip()])
    if result.stderr.strip():
        parts.extend(["stderr:", result.stderr.strip()])
    return "\n".join(parts)


def render_mermaid_offline(
    code: str,
    output_path: str | Path,
    *,
    output_format: str,
    debug_base_path: Path | None = None,
) -> bool:
    """Render a Mermaid block into an SVG or PNG asset.

    Args:
        code: Mermaid 源码。
        output_path: 输出文件路径。
        output_format: 输出格式，支持 `svg` 或 `png`。
        debug_base_path: 调试输出基础路径。

    Returns:
        bool: 渲染成功返回 `True`，否则返回 `False`。
    """
    cleaned_code = clean_mermaid_code(code)
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    cli_status = ensure_mermaid_cli()
    if not cli_status.available:
        extra_text = cli_status.message
        if cli_status.checked_paths:
            extra_text += "\nChecked paths:\n" + "\n".join(cli_status.checked_paths)
        save_failed_mermaid_source(cleaned_code, debug_base_path or output_file, extra_text=extra_text)
        logger.warning(cli_status.message)
        return False

    input_file = output_file.parent / f".tmp_mermaid_{uuid.uuid4().hex}.mmd"
    try:
        input_file.write_text(cleaned_code, encoding="utf-8")
        command = _build_mmdc_command(cli_status.path, input_file, output_file, output_format)
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=120,
                check=False,
                creationflags=creationflags,
            )
        except Exception as exc:
            save_failed_mermaid_source(
                cleaned_code,
                debug_base_path or output_file,
                extra_text=f"Failed to execute Mermaid CLI: {exc}",
            )
            logger.warning("Mermaid CLI execution failed: %s", exc)
            return False
    finally:
        input_file.unlink(missing_ok=True)

    if result.returncode != 0:
        save_failed_mermaid_source(
            cleaned_code,
            debug_base_path or output_file,
            extra_text=_build_mmdc_failure_details(command, result),
        )
        logger.warning("Mermaid CLI returned a non-zero exit code: %s", result.returncode)
        return False

    if not output_file.exists() or output_file.stat().st_size == 0:
        save_failed_mermaid_source(
            cleaned_code,
            debug_base_path or output_file,
            extra_text="Mermaid CLI completed without producing an output file.",
        )
        logger.warning("Mermaid CLI finished without producing output: %s", output_file)
        return False

    return True
