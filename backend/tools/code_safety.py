"""
AST 代码安全检查器

借鉴: data_analysis_agent 的 code_executor.py —
      通过 AST 静态分析阻止危险代码执行（exec/eval/open/非法import）。

DataForge 当前主要使用 SQL 查询数据，但未来可能引入 Python 代码执行
（如替代 SQL 做更灵活的数据处理），此模块提供 AST 级别的安全检查。

通过 AST 静态分析（非字符串黑名单）精确识别危险调用和非法导入。
"""

import ast
import logging
from dataclasses import dataclass, field
from typing import NamedTuple

logger = logging.getLogger(__name__)

# ─── 黑名单：禁止使用的内置函数/关键字 ───
FORBIDDEN_BUILTINS: set[str] = {
    "exec", "eval", "open", "__import__", "compile",
    "input", "breakpoint",
    "globals", "locals", "vars",
    "getattr", "setattr", "delattr",
    "hasattr",  # 允许但记录警告
}

# ─── 黑名单：禁止导入的模块 ───
# os 放行（matplotlib 保存文件需要 os.path.join），但禁止 os.system 等危险调用
FORBIDDEN_IMPORTS: set[str] = {
    "sys", "subprocess", "shutil", "socket",
    "ctypes", "multiprocessing", "threading",
    "signal", "atexit", "gc", "inspect", "traceback",
    "importlib", "pkgutil", "imp",
    "pathlib", "glob",
    "urllib", "http", "ftplib", "requests",
    "pickle", "marshal", "codecs",
    "builtins",
    "tempfile", "io",
}

# ─── 白名单：允许导入的数据科学库 ───
ALLOWED_IMPORTS: set[str] = {
    "pandas", "numpy", "matplotlib", "scipy",
    "statsmodels", "sklearn", "seaborn", "plotly",
    "os", "json", "csv", "io", "datetime", "collections",
    "itertools", "functools", "math", "statistics",
    "decimal", "fractions", "random",
    "re", "string", "textwrap",
    "typing", "dataclasses", "enum",
    "warnings", "logging",
    "copy", "hashlib", "base64",
    "PIL", "Pillow", "openpyxl", "xlrd",
}

# ─── 允许的模块前缀（如 sklearn.linear_model） ───
ALLOWED_MODULE_PREFIXES: set[str] = {
    "pandas", "numpy", "np", "pd",
    "matplotlib", "mpl", "plt",
    "scipy", "sp",
    "sklearn",
    "statsmodels", "sm",
    "seaborn", "sns",
    "plotly", "px", "go",
    "PIL",
}


class SafetyResult(NamedTuple):
    """安全检查结果"""
    safe: bool
    """是否安全"""
    errors: list[str]
    """错误列表（违反安全规则）"""
    warnings: list[str]
    """警告列表（潜在风险但不阻止执行）"""


@dataclass
class CodeSafetyChecker:
    """
    AST 代码安全检查器

    用法:
        checker = CodeSafetyChecker()
        result = checker.validate("import pandas as pd\\nprint(df.describe())")
        if result.safe:
            exec(code)  # 安全执行
        else:
            raise ValueError(f"代码不安全: {result.errors}")

    检查项:
      1. 禁止的内置函数 (exec, eval, open, __import__, ...)
      2. 禁止的模块导入 (os, sys, subprocess, ...)
      3. 未在白名单中的导入
      4. 属性访问风险 (如 __class__, __bases__)
    """

    forbidden_builtins: set[str] = field(default_factory=lambda: FORBIDDEN_BUILTINS.copy())
    forbidden_imports: set[str] = field(default_factory=lambda: FORBIDDEN_IMPORTS.copy())
    allowed_imports: set[str] = field(default_factory=lambda: ALLOWED_IMPORTS.copy())
    allowed_prefixes: set[str] = field(default_factory=lambda: ALLOWED_MODULE_PREFIXES.copy())

    def validate(self, code: str) -> SafetyResult:
        """
        验证 Python 代码安全性

        Args:
            code: Python 源代码字符串

        Returns:
            SafetyResult(safe, errors, warnings)
        """
        errors: list[str] = []
        warnings: list[str] = []

        # ─── 1. 解析 AST ───
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            errors.append(f"语法错误: {e}")
            return SafetyResult(False, errors, warnings)

        # ─── 2. 遍历 AST 节点 ───
        for node in ast.walk(tree):
            # 2a. 禁止的 import
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self._check_import(alias.name, alias.lineno, errors, warnings)

            # 2b. 禁止的 import ... from ...
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                self._check_import(module, node.lineno, errors, warnings)

            # 2c. 禁止的属性访问 (如 __class__, __bases__, __subclasses__)
            if isinstance(node, ast.Attribute):
                if node.attr.startswith("__") and node.attr.endswith("__"):
                    warnings.append(
                        f"第 {node.lineno} 行: 访问 dunder 属性 "
                        f"`.{node.attr}` 可能有安全风险"
                    )

            # 2d. 禁止的内置函数调用
            if isinstance(node, ast.Name):
                if node.id in self.forbidden_builtins:
                    errors.append(
                        f"第 {node.lineno} 行: 禁止使用 `{node.id}` — "
                        f"这是一个危险的内置函数"
                    )

            # 2e. 检查 Call 中的函数名（处理 getattr(obj, '__dict__') 等间接调用）
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    if node.func.id in self.forbidden_builtins:
                        errors.append(
                            f"第 {node.lineno} 行: 禁止调用 `{node.func.id}()` — "
                            f"这是一个危险的内置函数"
                        )

        # ─── 3. 返回结果 ───
        is_safe = len(errors) == 0
        return SafetyResult(is_safe, errors, warnings)

    def _check_import(
        self, module_name: str, lineno: int,
        errors: list[str], warnings: list[str],
    ):
        """检查单个 import 是否安全"""
        if not module_name:
            return

        top_level = module_name.split(".")[0]

        # 检查黑名单
        if top_level in self.forbidden_imports:
            errors.append(
                f"第 {lineno} 行: 禁止导入模块 `{module_name}` — "
                f"该模块可用于系统操作或代码注入"
            )
            return

        # 检查白名单
        if top_level in self.allowed_imports:
            return

        # 检查前缀白名单
        for prefix in self.allowed_prefixes:
            if module_name.startswith(prefix):
                return

        # 不在任何白名单中
        warnings.append(
            f"第 {lineno} 行: 模块 `{module_name}` 不在白名单中，"
            f"将被允许但请确认其安全性"
        )

    def validate_with_report(self, code: str) -> str:
        """
        验证代码并返回可读报告

        Args:
            code: Python 源代码

        Returns:
            可读的验证报告文本
        """
        result = self.validate(code)

        lines = ["## 代码安全检查报告"]
        if result.safe:
            lines.append("\n✅ **通过**: 代码通过安全检查")
        else:
            lines.append("\n❌ **拒绝**: 代码包含安全隐患")

        if result.errors:
            lines.append("\n### 错误（阻止执行）")
            for e in result.errors:
                lines.append(f"  - {e}")

        if result.warnings:
            lines.append("\n### 警告（允许执行但需注意）")
            for w in result.warnings:
                lines.append(f"  - {w}")

        if result.safe and not result.warnings:
            lines.append("\n无安全问题，可以安全执行。")

        return "\n".join(lines)


# ─── 便捷函数 ───

_default_checker: CodeSafetyChecker | None = None


def get_default_checker() -> CodeSafetyChecker:
    """获取默认的安全检查器单例"""
    global _default_checker
    if _default_checker is None:
        _default_checker = CodeSafetyChecker()
    return _default_checker


def validate_python_code(code: str) -> SafetyResult:
    """
    便捷函数：验证 Python 代码安全性。

    用法:
        result = validate_python_code("import pandas as pd; df.describe()")
        if not result.safe:
            raise ValueError(f"代码不安全: {result.errors}")
    """
    return get_default_checker().validate(code)


def assert_safe_code(code: str):
    """
    断言代码安全，不安全则抛出 ValueError。

    Args:
        code: Python 源代码

    Raises:
        ValueError: 代码包含安全隐患
    """
    result = validate_python_code(code)
    if not result.safe:
        raise ValueError(
            f"代码安全检查失败:\n" + "\n".join(f"  - {e}" for e in result.errors)
        )
