"""
Pydantic BaseSettings 配置系统


自动从 .env 文件和环境变量加载配置，提供类型校验和默认值。

v3.0 新增:
  - DATAFORGE_* 环境变量自动覆盖: 任何以 DATAFORGE_ 前缀的 env var
    会覆盖对应 Settings 字段。例如 DATAFORGE_LLM_PROVIDER=openai
    覆盖 llm_provider 字段。自动按字段类型转换值。
  - 优先级: DATAFORGE_* > .env > 字段默认值
"""

import logging
import os

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """全局配置，自动读取 .env 和环境变量"""

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
    }

    # ─── LLM ───
    llm_provider: str = Field(default="deepseek", description="LLM 供应商")
    deepseek_api_key: str = Field(default="", description="DeepSeek API Key")
    openai_api_key: str = Field(default="", description="OpenAI API Key")
    dashscope_api_key: str = Field(default="", description="阿里百炼 API Key")
    zhipu_api_key: str = Field(default="", description="智谱 API Key")
    siliconflow_api_key: str = Field(default="", description="SiliconFlow API Key")

    # ─── 数据库 ───
    db_path: str = Field(default="data/dataforge.db", description="SQLite 路径")
    data_dir: str = Field(default="data", description="CSV 数据目录")

    # ─── Agent 控制 ───
    max_sql_retries: int = Field(default=2, ge=0, le=5, description="SQL 重试上限")
    max_debate_rounds: int = Field(default=1, ge=1, le=5, description="辩论轮次上限")
    max_recur_limit: int = Field(default=50, ge=10, description="LangGraph 递归上限")

    # ─── 记忆 ───
    memory_enabled: bool = Field(default=True, description="启用上下文记忆")
    chroma_persist_dir: str = Field(default="data/chroma_db", description="ChromaDB 目录")

    # ─── 缓存 ───
    cache_enabled: bool = Field(default=True, description="启用缓存")
    cache_ttl_seconds: int = Field(default=3600, description="缓存过期时间(秒)")
    cache_max_size: int = Field(default=100, description="内存缓存条目上限")

    # ─── 限流 ───
    rate_limit_enabled: bool = Field(default=True, description="启用速率限制")
    rate_limit_max_requests: int = Field(default=30, description="每分钟最大请求数")

    # ─── 日志 ───
    log_level: str = Field(default="INFO", description="日志级别")
    log_dir: str = Field(default="logs", description="日志目录")

    # ─── 调试模式 ───
    strict_mode: bool = Field(
        default=False,
        description="严格模式：非网络异常直接抛出（开发期暴露配置/数据错误）",
    )

    # ─── 鉴权 ───
    api_key: str = Field(default="", description="API Key（空则不验证，方便开发）")

    # ─── 服务 ───
    host: str = Field(default="127.0.0.1")
    port: int = Field(default=4433)
    cors_origins: list[str] = Field(
        default=["http://localhost:5173", "http://localhost:4433", "http://127.0.0.1:5173"],
        description="允许的跨域来源",
    )

    @model_validator(mode="before")
    @classmethod
    def apply_dataforge_overrides(cls, values: dict) -> dict:
        """
        自动检测 DATAFORGE_* 环境变量并覆盖对应 Settings 字段。

        DATAFORGE_LLM_PROVIDER → 覆盖 llm_provider
        DATAFORGE_DB_PATH → 覆盖 db_path
        DATAFORGE_MAX_SQL_RETRIES → 覆盖 max_sql_retries（自动转为 int）

        优先级: DATAFORGE_* > .env > 字段默认值

        自动按字段声明的类型进行值转换（bool/int/float/list/str）。
        """
        prefix = "DATAFORGE_"

        # 构建字段名映射: 大写 → 原始名
        field_map = {}
        for fname in cls.model_fields.keys():
            field_map[fname.upper()] = fname

        for env_key, env_val in os.environ.items():
            if not env_key.startswith(prefix):
                continue
            suffix = env_key[len(prefix):]  # e.g. "MAX_SQL_RETRIES"
            field_name = field_map.get(suffix)
            if field_name is None:
                continue  # 不匹配任何已知字段，跳过

            # 自动类型转换
            field_info = cls.model_fields[field_name]
            annotation = field_info.annotation

            try:
                if annotation is bool or getattr(annotation, "__origin__", None) is bool:
                    coerced = env_val.lower() in ("1", "true", "yes", "on")
                elif annotation is int:
                    coerced = int(env_val)
                elif annotation is float:
                    coerced = float(env_val)
                elif annotation is list or annotation is list[str] or (
                    hasattr(annotation, "__origin__") and annotation.__origin__ is list
                ):
                    coerced = [x.strip() for x in env_val.split(",") if x.strip()]
                else:
                    coerced = env_val

                logger.info(
                    "[Config] DATAFORGE override: %s = %s (from env)",
                    field_name, coerced,
                )
                values[field_name] = coerced
            except (ValueError, TypeError) as e:
                logger.warning(
                    "[Config] DATAFORGE_%s 类型转换失败 (%s)，使用默认值",
                    suffix, e,
                )

        return values

    def validate_api_keys(self) -> list[str]:
        """检查至少有一个 API Key 已配置，返回缺失的 Provider 列表。
        若 strict_mode=True 且有 Provider 缺失，直接抛出 ValueError。"""
        provider_key_map = {
            "deepseek": self.deepseek_api_key,
            "openai": self.openai_api_key,
            "qwen": self.dashscope_api_key,
            "glm": self.zhipu_api_key,
            "siliconflow": self.siliconflow_api_key,
        }
        missing = [
            p
            for p, key in provider_key_map.items()
            if not key or key.startswith("sk-xxx") or "your_" in key
        ]
        if missing and self.strict_mode:
            raise ValueError(
                f"Strict 模式下缺少 API Key: {missing}。请设置对应环境变量或关闭 strict_mode。"
            )
        return missing


# 全局单例
# Pydantic BaseSettings 天然单例 — .env 文件只加载一次。
# 保留 get_settings() 提供缓存实例，reset_settings() 用于测试隔离。
_settings: Settings | None = None


def get_settings() -> Settings:
    """获取全局配置实例（缓存）"""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings():
    """重置配置实例（测试隔离用）"""
    global _settings
    _settings = None
