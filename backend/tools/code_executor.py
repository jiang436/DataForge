"""
Python 代码执行器 — 状态化执行环境

借鉴 data_analysis_agent 的 CodeExecutor:
  - IPython InteractiveShell 提供变量跨代码块持久化
  - matplotlib Agg backend + 中文字体预配置
  - AST 安全审查（复用 code_safety.py）
  - 图片保存到会话目录 + 返回绝对路径

降级策略:
  - IPython 可用时使用 InteractiveShell（推荐，变量自然保持）
  - IPython 不可用时使用 shared globals() + exec()（轻量降级）

用法:
    executor = get_executor(session_dir="output/session_abc123/")
    result = executor.execute("plt.plot([1,2,3]); plt.savefig(...)")
    # result = {"success": True, "output": "...", "figures": [".../figure_1.png"], ...}
"""

import io
import logging
import os
import sys
import traceback
from pathlib import Path
from typing import Any

from backend.tools.code_safety import get_default_checker

logger = logging.getLogger(__name__)

# ─── 可选依赖 ───
try:
    from IPython.core.interactiveshell import InteractiveShell
    from IPython.utils.capture import capture_output as ipython_capture

    _HAS_IPYTHON = True
except ImportError:
    _HAS_IPYTHON = False
    logger.info("IPython 未安装，使用 shared-globals exec() 降级方案（功能等同）")

try:
    import matplotlib

    matplotlib.use("Agg")  # 无头渲染，必须在 import pyplot 之前
    import matplotlib.pyplot as plt

    _HAS_MATPLOTLIB = True
except ImportError:
    _HAS_MATPLOTLIB = False
    logger.warning("matplotlib 未安装，图表功能不可用")

# ─── 中文字体探测 ───
_CHINESE_FONTS: list[str] = []
if _HAS_MATPLOTLIB:
    import matplotlib.font_manager as fm

    _available = {f.name for f in fm.fontManager.ttflist}
    for _font in ["SimHei", "Microsoft YaHei", "WenQuanYi Micro Hei",
                   "Noto Sans CJK SC", "PingFang SC", "Arial Unicode MS", "DejaVu Sans"]:
        if _font in _available:
            _CHINESE_FONTS.append(_font)
    if _CHINESE_FONTS:
        plt.rcParams["font.sans-serif"] = _CHINESE_FONTS + ["DejaVu Sans"]
        plt.rcParams["axes.unicode_minus"] = False
        logger.info("中文字体: %s", _CHINESE_FONTS[:3])
    else:
        logger.warning("未检测到中文字体，中文图表可能显示为方框。建议安装 SimHei 或 Microsoft YaHei。")


class CodeExecutor:
    """
    状态化 Python 代码执行器

    借鉴 data_analysis_agent 的 CodeExecutor:
      - 变量跨代码块持久化（IPython/ shared globals）
      - matplotlib 环境预配置
      - AST 安全生产检查
      - 自动捕获 stdout + 保存的图片路径

    LLM 可以像在 Jupyter Notebook 中一样编写 matplotlib 代码，变量跨代码块保持。
    """

    # 预导入的库名清单（启动时自动注入执行环境）
    COMMON_IMPORTS = """
import pandas as pd
import numpy as np
import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
"""

    MATPLOTLIB_IMPORTS = """
import matplotlib
matplotlib.use('Agg')
import warnings
warnings.filterwarnings('ignore', category=UserWarning, message='.*Glyph.*missing.*')
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import matplotlib.gridspec as gridspec
"""

    def __init__(self, session_dir: str = "output"):
        """
        Args:
            session_dir: 会话输出目录（图片保存到这里）
        """
        self.session_dir = Path(session_dir).resolve()
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.figure_counter = 0

        if _HAS_IPYTHON:
            self._init_ipython()
        else:
            self._init_shared_globals()

        # 注入会话目录变量
        self.set_variable("session_output_dir", str(self.session_dir))

        logger.info(
            "[CodeExecutor] 初始化完成 (IPython=%s, matplotlib=%s, session=%s)",
            _HAS_IPYTHON, _HAS_MATPLOTLIB, self.session_dir.name,
        )

    # ─── IPython 模式 ───

    def _init_ipython(self):
        """IPython InteractiveShell 初始化"""
        self.shell = InteractiveShell.instance()
        self.shell.run_cell(self.COMMON_IMPORTS)
        if _HAS_MATPLOTLIB:
            self.shell.run_cell("import warnings; warnings.filterwarnings('ignore', category=UserWarning, message='.*Glyph.*missing.*')")
            self.shell.run_cell(self.MATPLOTLIB_IMPORTS)
            # 中文字体
            if _CHINESE_FONTS:
                fonts_str = str(_CHINESE_FONTS[:5])
                self.shell.run_cell(
                    f"plt.rcParams['font.sans-serif'] = {fonts_str} + ['DejaVu Sans']\n"
                    "plt.rcParams['axes.unicode_minus'] = False"
                )

    # ─── Shared Globals 降级模式 ───

    def _init_shared_globals(self):
        """exec() 降级：维护共享 __globals__ dict 实现变量持久化"""
        self._globals: dict[str, Any] = {"__builtins__": __builtins__}
        self._exec(self.COMMON_IMPORTS)
        if _HAS_MATPLOTLIB:
            self._exec(self.MATPLOTLIB_IMPORTS)
            if _CHINESE_FONTS:
                self._exec(
                    f"plt.rcParams['font.sans-serif'] = {_CHINESE_FONTS[:5]!r} + ['DejaVu Sans']\n"
                    "plt.rcParams['axes.unicode_minus'] = False"
                )

    def _exec(self, code: str):
        """在共享 globals 中执行代码"""
        exec(code, self._globals)

    # ─── 公共接口 ───

    def set_variable(self, name: str, value: Any):
        """注入变量到执行环境"""
        if _HAS_IPYTHON:
            self.shell.user_ns[name] = value
        else:
            self._globals[name] = value

    def get_variable(self, name: str) -> Any:
        """从执行环境读取变量"""
        if _HAS_IPYTHON:
            return self.shell.user_ns.get(name)
        return self._globals.get(name)

    def get_environment_info(self) -> str:
        """
        快照当前命名空间 → 注入 LLM prompt。

        借鉴 data_analysis_agent: 每轮推理前告诉 LLM 当前有哪些
        DataFrame、变量、已保存的图表，让它感知"运行时状态"。
        """
        ns = self.shell.user_ns if _HAS_IPYTHON else self._globals
        parts = []

        dfs = []
        for name, val in ns.items():
            if name.startswith("_"):
                continue
            if hasattr(val, "shape") and hasattr(val, "head"):
                dfs.append(f"  DataFrame `{name}`: {val.shape[0]}行×{val.shape[1]}列")
            elif name == "session_output_dir":
                parts.append(f"  会话输出目录: {val}")

        if dfs:
            parts.append("**可用数据框**:")
            parts.extend(dfs)

        if _HAS_MATPLOTLIB:
            fig_nums = plt.get_fignums()
            if fig_nums:
                parts.append(f"  matplotlib 图形: {len(fig_nums)} 个未关闭")

        # 已保存的图表
        pngs = sorted(self.session_dir.glob("*.png"))
        if pngs:
            parts.append(f"**已保存图表** ({len(pngs)} 个):")
            for p in pngs[-10:]:  # 最近10个
                parts.append(f"  {p.name}")

        return "\n".join(parts) if parts else "（初始状态，无可用变量或图表）"

    def execute(self, code: str) -> dict[str, Any]:
        """
        执行 Python 代码并返回结果。

        Args:
            code: Python 源代码

        Returns:
            {
                "success": bool,
                "output": str,       # stdout 输出
                "error": str,        # 错误信息（成功时为空）
                "figures": [str],    # 本次执行新增的图片绝对路径
                "variables": dict,   # 新生成的 DataFrame 等变量摘要
            }
        """
        # ─── AST 安全检查 ───
        checker = get_default_checker()
        safety = checker.validate(code)
        if not safety.safe:
            return {
                "success": False,
                "output": "",
                "error": f"代码安全检查失败:\n" + "\n".join(f"  - {e}" for e in safety.errors),
                "figures": [],
                "variables": {},
            }

        # ─── 记录执行前的图片清单 ───
        pngs_before = set(self.session_dir.glob("*.png"))

        # ─── 记录执行前的变量 ───
        ns = self.shell.user_ns if _HAS_IPYTHON else self._globals
        vars_before = {k for k in ns if not k.startswith("_")}

        # ─── 执行 ───
        stdout = io.StringIO()
        stderr = io.StringIO()

        try:
            if _HAS_IPYTHON:
                with ipython_capture() as captured:
                    result = self.shell.run_cell(code)
                output = captured.stdout or ""

                if result.error_before_exec:
                    return self._error_response(f"执行前错误: {result.error_before_exec}", stdout)
                if result.error_in_exec:
                    return self._error_response(
                        f"{type(result.error_in_exec).__name__}: {result.error_in_exec}", output
                    )
                if result.result is not None:
                    formatted = self._format_result(result.result)
                    if formatted:
                        output += "\n" + formatted
            else:
                old_stdout, old_stderr = sys.stdout, sys.stderr
                sys.stdout, sys.stderr = stdout, stderr
                try:
                    self._exec(code)
                finally:
                    sys.stdout, sys.stderr = old_stdout, old_stderr
                output = stdout.getvalue()
                err_output = stderr.getvalue()
                if err_output:
                    return self._error_response(err_output.strip(), output)
        except Exception as e:
            return self._error_response(f"{type(e).__name__}: {e}\n{traceback.format_exc()}",
                                        stdout.getvalue() if not _HAS_IPYTHON else "")

        # ─── 检测新图片 ───
        pngs_after = set(self.session_dir.glob("*.png"))
        new_figures = sorted(
            str(p.resolve()) for p in (pngs_after - pngs_before)
        )

        # ─── 检测新变量 ───
        vars_after = {k for k in ns if not k.startswith("_")}
        new_vars = {}
        for var_name in vars_after - vars_before:
            val = ns.get(var_name)
            if hasattr(val, "shape") and hasattr(val, "head"):
                new_vars[var_name] = f"{type(val).__name__}: {val.shape[0]}行×{val.shape[1]}列"
            elif isinstance(val, (int, float, str)):
                new_vars[var_name] = f"{type(val).__name__}: {str(val)[:100]}"

        # ─── 关闭所有图形（防止内存泄漏） ───
        if _HAS_MATPLOTLIB:
            try:
                # 不关闭——让 LLM 可以跨轮迭代修改同一张图
                # plt.close('all')  # 需要 LLM 显式调用
                pass
            except Exception:
                pass

        return {
            "success": True,
            "output": output.strip(),
            "error": "",
            "figures": new_figures,
            "variables": new_vars,
        }

    def _error_response(self, error: str, output: str) -> dict[str, Any]:
        return {
            "success": False,
            "output": output.strip() if output else "",
            "error": error[:2000],
            "figures": [],
            "variables": {},
        }

    def _format_result(self, obj: Any) -> str:
        """格式化 IPython 返回值 —— 借鉴 data_analysis_agent 的智能截断"""
        if hasattr(obj, "shape") and hasattr(obj, "head"):
            rows, cols = obj.shape
            if rows <= 15:
                return str(obj)
            return (
                f"{obj.head(5)}\n...\n(省略 {rows - 10} 行)\n...\n{obj.tail(5)}"
            )
        if isinstance(obj, (int, float, str, bool)):
            return str(obj)[:500]
        return str(obj)[:500]

    def reset(self):
        """重置执行环境"""
        if _HAS_IPYTHON:
            self.shell.reset()
            self._init_ipython()
        else:
            self._init_shared_globals()
        self.set_variable("session_output_dir", str(self.session_dir))
        self.figure_counter = 0
        logger.info("[CodeExecutor] 环境已重置")


# ─── 模块级单例（contextvars 隔离，支持多租户） ───

import contextvars

_executor_ctx: contextvars.ContextVar = contextvars.ContextVar("code_executor", default=None)


def get_executor(session_dir: str = "output") -> CodeExecutor:
    """获取当前上下文的 CodeExecutor 单例"""
    executor = _executor_ctx.get()
    if executor is None:
        executor = CodeExecutor(session_dir=session_dir)
        _executor_ctx.set(executor)
    return executor


def reset_executor():
    """重置当前上下文的 CodeExecutor"""
    executor = _executor_ctx.get()
    if executor:
        executor.reset()
    _executor_ctx.set(None)
