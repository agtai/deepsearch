# -*- coding: UTF-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2025. All rights reserved.
"""
沙箱代码执行器 — 子进程隔离版

通过独立 Python 子进程执行 LLM 生成的代码，确保主进程的环境隔离与安全。

安全机制：
1. 进程隔离  — 代码在独立子进程中运行，崩溃 / 内存泄漏不影响主进程
2. 模块限制  — import hook 拦截危险模块（subprocess, shutil, ctypes 等）
3. 写入限制  — 仅允许向工作目录及系统临时目录写入文件
4. 系统调用限制 — 禁用 os.system, os.popen 等可执行外部命令的函数
5. 超时控制  — 执行超时自动 SIGKILL 终止子进程
"""

import asyncio
import json
import logging
import os
import sys
import uuid
from typing import Any, Dict

_sandbox_logger = logging.getLogger(__name__)

RESTRICTED_MODULES = frozenset(
    {
        "subprocess",
        "shutil",
        "ctypes",
        "signal",
        "multiprocessing",
        "socket",
        "http.server",
        "xmlrpc",
        "ftplib",
        "smtplib",
        "webbrowser",
        "code",
        "codeop",
        "compileall",
    }
)

DEFAULT_EXEC_TIMEOUT = 120

_FONT_CANDIDATES = [
    os.path.join(os.path.dirname(__file__), "..", "fonts", "kt_font.ttf"),
    os.path.join(
        "openjiuwen_deepsearch", "algorithm", "chart_generation", "fonts", "kt_font.ttf"
    ),
]

# ────────────────────────────────────────────────────────────────
# Worker script — 在隔离子进程中执行，通过 stdin 注入
# ────────────────────────────────────────────────────────────────
_WORKER_SCRIPT = r'''
import sys, os, json, builtins, traceback, tempfile, importlib

_cfg = json.loads(os.environ["_SANDBOX_CFG"])
_working_dir = os.path.abspath(_cfg["working_dir"])
_variables   = _cfg.get("variables", {})
_restricted  = frozenset(_cfg.get("restricted_modules", []))
_font_path   = _cfg.get("font_path", "")
_code_path   = _cfg["code_path"]

# ════════════════════════════════════════════════════════════════
# Phase 1: 在无任何限制的环境下预加载所有受信任的科学计算库
#   matplotlib / numpy / pandas / seaborn 等库在初始化时会内部
#   import shutil, ctypes, signal 等模块；这些属于库的实现细节，
#   必须在安全限制激活之前完成加载。
#   每个库独立 try/except，避免一个失败导致后续库都跳过。
# ════════════════════════════════════════════════════════════════
import os as _os
_orig_open = builtins.open

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager as _fm
    if _font_path and _os.path.isfile(_font_path):
        _fm.fontManager.addfont(_font_path)
        _font_name = _fm.FontProperties(fname=_font_path).get_name()
        plt.rcParams["font.family"] = _font_name
    matplotlib.rcParams["axes.unicode_minus"] = False
except Exception:
    pass

try:
    import numpy
except Exception:
    pass

try:
    import pandas
except Exception:
    pass

try:
    import seaborn
except Exception:
    pass

# ════════════════════════════════════════════════════════════════
# Phase 2: 所有受信任库已加载完毕，现在激活安全限制
#   限制只约束后续执行的"用户代码"，不影响已加载的库内部逻辑。
# ════════════════════════════════════════════════════════════════

# ── Import restriction ──────────────────────────────────────────
_orig_import = builtins.__import__

def _safe_import(name, *args, **kwargs):
    if name.split(".")[0] in _restricted:
        raise ImportError(f"Importing '{name}' is not allowed in the code sandbox.")
    return _orig_import(name, *args, **kwargs)

builtins.__import__ = _safe_import

_orig_import_module = importlib.import_module

def _safe_import_module(name, package=None):
    if name.split(".")[0] in _restricted:
        raise ImportError(f"Importing '{name}' is not allowed in the code sandbox.")
    return _orig_import_module(name, package)

importlib.import_module = _safe_import_module

# ── File write restriction ──────────────────────────────────────
_write_dirs = [_working_dir, os.path.abspath(tempfile.gettempdir())]
_home_cache = os.path.join(os.path.expanduser("~"), ".cache")
if os.path.isdir(_home_cache):
    _write_dirs.append(os.path.abspath(_home_cache))

def _safe_open(file, mode="r", *a, **kw):
    if any(m in mode for m in ("w", "a", "x", "+")):
        _abs = os.path.abspath(str(file))
        if not any(_abs == d or _abs.startswith(d + os.sep) for d in _write_dirs):
            raise PermissionError(
                f"Writing to '{file}' is not allowed. "
                f"Sandbox writes restricted to: {_write_dirs}"
            )
    return _orig_open(file, mode, *a, **kw)

builtins.open = _safe_open

# ── Dangerous os functions ──────────────────────────────────────
for _fn_name in (
    "system", "popen",
    "execl", "execle", "execlp", "execlpe",
    "execv", "execve", "execvp", "execvpe",
    "spawnl", "spawnle", "spawnlp", "spawnlpe",
    "spawnv", "spawnve", "spawnvp", "spawnvpe",
    "kill", "killpg",
):
    if hasattr(_os, _fn_name):
        def _blocked(*a, _n=_fn_name, **kw):
            raise PermissionError(f"os.{_n}() is not allowed in the sandbox.")
        setattr(_os, _fn_name, _blocked)

# ════════════════════════════════════════════════════════════════
# Phase 3: 构建 exec 命名空间并执行用户代码
#   将 Phase 1 预加载的模块注入到 exec 命名空间中，确保用户代码
#   即使缺少 import 语句也能直接使用常用库名称。
#   例如 LLM 可能写 `import matplotlib.pyplot as plt` 然后直接
#   用 `matplotlib.use('Agg')`——`as` 语法只绑定 `plt`，不绑定
#   `matplotlib`，如果不预注入就会 NameError。
# ════════════════════════════════════════════════════════════════
_ns = {"__builtins__": builtins}

_inject_map = {
    "os": "os", "json": "json", "math": "math", "re": "re",
    "matplotlib": "matplotlib",
    "plt": "matplotlib.pyplot",
    "fm": "matplotlib.font_manager",
    "font_manager": "matplotlib.font_manager",
    "np": "numpy", "numpy": "numpy",
    "pd": "pandas", "pandas": "pandas",
    "sns": "seaborn", "seaborn": "seaborn",
}
for _alias, _mod_name in _inject_map.items():
    if _mod_name in sys.modules:
        _ns[_alias] = sys.modules[_mod_name]

for _k, _v in _variables.items():
    _ns[_k] = _v

with _orig_open(_code_path, "r", encoding="utf-8") as _f:
    _user_code = _f.read()

try:
    exec(compile(_user_code, "<sandbox>", "exec"), _ns)
except Exception:
    traceback.print_exc()
    sys.exit(1)
finally:
    try:
        import matplotlib.pyplot as _plt
        _plt.close("all")
    except Exception:
        pass
'''


def _resolve_font_path() -> str:
    """定位 kt_font.ttf 字体文件，按候选路径依次查找。"""
    for candidate in _FONT_CANDIDATES:
        abs_path = os.path.abspath(candidate)
        if os.path.isfile(abs_path):
            return abs_path
    return ""


class AsyncCodeExecutor:
    """
    子进程隔离的 Python 代码沙箱。

    每次 execute() 启动一个独立 Python 子进程来执行代码:
    - 主进程环境不受污染（变量、模块、matplotlib 状态等）
    - 代码崩溃/段错误不影响主进程
    - 内存泄漏随子进程退出自动回收
    - 通过 set_variable() 注入的变量以 JSON 序列化方式传递给子进程
    """

    def __init__(self, working_dir: str, exec_timeout: float = DEFAULT_EXEC_TIMEOUT):
        self.working_dir = os.path.abspath(working_dir)
        self.exec_timeout = exec_timeout
        self.session_id = str(uuid.uuid4())
        self._variables: Dict[str, Any] = {}
        self._font_path = _resolve_font_path()
        os.makedirs(self.working_dir, exist_ok=True)

    def set_variable(self, name: str, value: Any):
        """注入变量到沙箱执行命名空间。"""
        self._variables[name] = value

    def get_variable(self, name: str) -> Any:
        """获取已注入的变量值。"""
        return self._variables.get(name)

    async def execute(self, code: str) -> dict:
        """
        在隔离子进程中执行代码。

        流程：
        1. 将用户代码写入临时 .py 文件
        2. 通过环境变量传递沙箱配置（变量、受限模块、字体路径等）
        3. 启动子进程，通过 stdin 注入 worker 引导脚本
        4. worker 在子进程中设置安全限制后执行用户代码
        5. 捕获 stdout/stderr，超时则 SIGKILL 终止

        Returns:
            {"stdout": str, "stderr": str, "error": bool}
        """
        tag = uuid.uuid4().hex[:12]
        code_path = os.path.join(self.working_dir, f"_sandbox_{tag}.py")

        try:
            with open(code_path, "w", encoding="utf-8") as f:
                f.write(code)

            config = {
                "working_dir": self.working_dir,
                "variables": self._safe_serialize(self._variables),
                "restricted_modules": list(RESTRICTED_MODULES),
                "font_path": self._font_path,
                "code_path": os.path.abspath(code_path),
            }

            env = os.environ.copy()
            env["_SANDBOX_CFG"] = json.dumps(config, ensure_ascii=False, default=str)

            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                "-",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )

            try:
                stdout_raw, stderr_raw = await asyncio.wait_for(
                    proc.communicate(input=_WORKER_SCRIPT.encode("utf-8")),
                    timeout=self.exec_timeout,
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return {
                    "stdout": "",
                    "stderr": (
                        f"ExecutionTimeout: code execution exceeded "
                        f"{self.exec_timeout}s limit\n"
                    ),
                    "error": True,
                }

            stdout = stdout_raw.decode("utf-8", errors="replace")
            stderr = stderr_raw.decode("utf-8", errors="replace")

            return {
                "stdout": stdout if stdout.strip() else "Run completed with no output.",
                "stderr": stderr,
                "error": proc.returncode != 0,
            }

        except Exception as exc:
            _sandbox_logger.error("Sandbox launch failed: %s", exc, exc_info=True)
            return {
                "stdout": "",
                "stderr": f"SandboxError: [{type(exc).__name__}] {exc}\n",
                "error": True,
            }
        finally:
            try:
                os.unlink(code_path)
            except OSError:
                pass

    @staticmethod
    def _safe_serialize(variables: Dict[str, Any]) -> dict:
        """将变量序列化为 JSON 兼容的 dict，不可序列化的值转为字符串表示。"""
        result = {}
        for name, value in variables.items():
            try:
                json.dumps(value, ensure_ascii=False)
                result[name] = value
            except (TypeError, ValueError):
                result[name] = str(value)
        return result

    def get_environment_info(self) -> str:
        """描述当前沙箱环境信息，用于 prompt 构建。"""
        parts = [
            "Sandbox environment (subprocess-isolated):",
            f"  working_dir: {self.working_dir}",
            f"  font_path: {self._font_path or '(not found)'}",
            "  pre-configured: matplotlib(Agg backend), Chinese font (kt_font.ttf)",
            "  available libraries: pandas, numpy, matplotlib, seaborn",
        ]
        if self._variables:
            parts.append("  injected variables:")
            for k, v in self._variables.items():
                parts.append(f"    {k} = {v!r}")
        return "\n".join(parts)
