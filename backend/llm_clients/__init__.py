"""
LLM 客户端包

参考: tradingagents/llm_clients/__init__.py

用法:
    from backend.llm_clients import create_quick_llm, create_deep_llm
"""

from backend.llm_clients.factory import (
    FallbackChatOpenAI,
    create_deep_llm,
    create_llm,
    create_quick_llm,
)
from backend.llm_clients.model_catalog import MODEL_CATALOG, get_provider_list
from backend.llm_clients.provider_keys import PROVIDER_ALIASES, PROVIDER_CONFIG

__all__ = [
    "create_llm",
    "create_quick_llm",
    "create_deep_llm",
    "FallbackChatOpenAI",
    "PROVIDER_CONFIG",
    "PROVIDER_ALIASES",
    "MODEL_CATALOG",
    "get_provider_list",
]
