"""
Agent 模块 — 懒加载导出


用法:
    from backend.agent import create_planner, create_sql_agent
"""

import importlib

_EXPORTS: dict[str, tuple[str, str]] = {
    # ─── 工具调用型 ───
    "create_sql_agent": ("backend.agent.analysts.sql_agent", "create_sql_agent"),
    "create_chart_agent": ("backend.agent.analysts.chart_agent", "create_chart_agent"),
    # ─── 辩论型 ───
    "create_optimist": ("backend.agent.debaters.optimist", "create_optimist"),
    "create_pessimist": ("backend.agent.debaters.pessimist", "create_pessimist"),
    # ─── 决策型 ───
    "create_planner": ("backend.agent.managers.planner", "create_planner"),
    "create_validator": ("backend.agent.managers.validator", "create_validator"),
    # ─── 合成型 ───
    "create_report_agent": ("backend.agent.synthesis.report_agent", "create_report_agent"),
    # ─── 共享 ───
    "DataAnalysisState": ("backend.agent.utils.state", "DataAnalysisState"),
    "DebateState": ("backend.agent.utils.state", "DebateState"),
}

__all__ = list(_EXPORTS.keys())


def __getattr__(name: str):
    """懒加载 — 只在第一次访问时导入"""
    if name not in _EXPORTS:
        raise AttributeError(f"模块 'backend.agent' 没有属性 '{name}'")
    module_name, attr_name = _EXPORTS[name]
    module = importlib.import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals().keys()) | set(_EXPORTS.keys()))
