"""
模型目录

参考: tradingagents/llm_clients/model_catalog.py

每个 Provider 的快速/深度模型分层列表，供前端下拉选择。
"""

MODEL_CATALOG = {
    "deepseek": {
        "name": "DeepSeek",
        "models": {
            "quick": ["deepseek-chat"],
            "deep": ["deepseek-chat", "deepseek-reasoner"],
        },
    },
    "qwen": {
        "name": "阿里百炼",
        "models": {
            "quick": ["qwen-turbo", "qwen-plus"],
            "deep": ["qwen-plus", "qwen-max"],
        },
    },
    "glm": {
        "name": "智谱 GLM",
        "models": {
            "quick": ["glm-4-flash"],
            "deep": ["glm-4-plus", "glm-4"],
        },
    },
    "openai": {
        "name": "OpenAI",
        "models": {
            "quick": ["gpt-4o-mini"],
            "deep": ["gpt-4o", "gpt-4.1-mini"],
        },
    },
    "siliconflow": {
        "name": "SiliconFlow",
        "models": {
            "quick": ["Qwen/Qwen2.5-7B-Instruct"],
            "deep": ["Qwen/Qwen2.5-72B-Instruct", "deepseek-ai/DeepSeek-V3"],
        },
    },
}


def get_provider_list() -> list[dict]:
    """返回可供前端选择的 Provider 列表"""
    return [{"key": k, "name": v["name"]} for k, v in MODEL_CATALOG.items()]


def get_models_for_provider(provider: str, tier: str = "quick") -> list[str]:
    """获取指定 Provider 的模型列表"""
    provider_data = MODEL_CATALOG.get(provider, {})
    return provider_data.get("models", {}).get(tier, [])
