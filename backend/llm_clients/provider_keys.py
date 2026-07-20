"""
Provider 配置与密钥管理


集中管理所有 Provider 的 base_url、env_key、别名映射。
添加新 Provider 只需在此文件加一条记录。
"""

# ─── Provider 配置表 ───
# 每个 Provider 可配置 fallback_url + fallback_env_key 用于故障转移。
# 当主端点限流/故障时，自动切换到备用端点，提升可用性。

PROVIDER_CONFIG = {
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "env_key": "DEEPSEEK_API_KEY",
        "default_model": "deepseek-chat",
        # 备用端点：SiliconFlow 作为 DeepSeek 的 failover
        "fallback_url": "https://api.siliconflow.cn/v1",
        "fallback_env_key": "SILICONFLOW_API_KEY",
        "fallback_model": "deepseek-ai/DeepSeek-V3",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "env_key": "OPENAI_API_KEY",
        "default_model": "gpt-4o-mini",
        # OpenAI 备用：Azure OpenAI 或兼容网关
        "fallback_url": "",
        "fallback_env_key": "",
        "fallback_model": "",
    },
    "qwen": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "env_key": "DASHSCOPE_API_KEY",
        "default_model": "qwen-plus",
        "fallback_url": "",
        "fallback_env_key": "",
        "fallback_model": "",
    },
    "glm": {
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "env_key": "ZHIPU_API_KEY",
        "default_model": "glm-4-flash",
        "fallback_url": "",
        "fallback_env_key": "",
        "fallback_model": "",
    },
    "siliconflow": {
        "base_url": "https://api.siliconflow.cn/v1",
        "env_key": "SILICONFLOW_API_KEY",
        "default_model": "Qwen/Qwen2.5-7B-Instruct",
        "fallback_url": "",
        "fallback_env_key": "",
        "fallback_model": "",
    },
}

# Provider 别名
PROVIDER_ALIASES = {
    "dashscope": "qwen",
    "alibaba": "qwen",
    "zhipu": "glm",
}


def normalize_provider(provider: str) -> str:
    """标准化 Provider 名称，处理别名"""
    p = provider.lower().strip()
    return PROVIDER_ALIASES.get(p, p)


def env_key_for_provider(provider: str) -> str:
    """获取 Provider 对应的环境变量名"""
    p = normalize_provider(provider)
    return PROVIDER_CONFIG.get(p, {}).get("env_key", "")
