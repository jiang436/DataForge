"""
Graph 模块 — 懒加载导出


用法:
    from backend.graph import DataAgentGraph, GraphSetup, ConditionalLogic, Propagator
"""

import importlib

_EXPORTS: dict[str, tuple[str, str]] = {
    "DataAgentGraph": ("backend.graph.orchestrator", "DataAgentGraph"),
    "GraphSetup": ("backend.graph.graph_setup", "GraphSetup"),
    "ConditionalLogic": ("backend.graph.conditional_logic", "ConditionalLogic"),
    "Propagator": ("backend.graph.propagation", "Propagator"),
}

__all__ = list(_EXPORTS.keys())


def __getattr__(name: str):
    if name not in _EXPORTS:
        raise AttributeError(f"模块 'backend.graph' 没有属性 '{name}'")
    module_name, attr_name = _EXPORTS[name]
    module = importlib.import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals().keys()) | set(_EXPORTS.keys()))
