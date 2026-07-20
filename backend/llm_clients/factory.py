"""
LLM 客户端工厂


提供统一接口创建 LLM 实例，一行代码切换 Provider。
内置 Token 用量追踪。
v3.1: 新增双端点故障转移（FallbackChatOpenAI）+ 指数退避重试。
"""

import contextvars
import logging
import os
import threading
import time

from langchain_core.messages import AIMessage, BaseMessage
from langchain_openai import ChatOpenAI

from backend.llm_clients.provider_keys import (
    PROVIDER_CONFIG,
    normalize_provider,
)

logger = logging.getLogger(__name__)

# ─── 可重试的异常类型 ───
# 这些异常表示临时性网络/服务问题，重试有意义
# 内容审查错误不重试（重试也不会改变结果）
RETRYABLE_EXCEPTIONS: tuple = ()
try:
    from openai import (
        APIConnectionError,
        APITimeoutError,
        InternalServerError,
        RateLimitError,
    )
    RETRYABLE_EXCEPTIONS = (APIConnectionError, APITimeoutError, InternalServerError, RateLimitError)
except ImportError:
    pass


class FallbackChatOpenAI:
    """
    带故障转移的 ChatOpenAI 包装器。

    借鉴: data_analysis_agent 的 AsyncFallbackOpenAIClient —
          主端点调用失败 → 指数退避重试 → 切换备用端点

    特性:
      - 指数退避重试（1s, 2s, 4s...）
      - 主端点失败后自动切换到备用端点
      - 透明代理：对外接口与 ChatOpenAI 一致
      - 记录故障转移事件供监控

    主端点失败后自动切换备用端点，配合指数退避重试，提升系统可用性。
    """

    def __init__(
        self,
        primary_llm: ChatOpenAI,
        fallback_llm: ChatOpenAI | None = None,
        max_retries: int = 3,
        base_delay: float = 1.0,
    ):
        """
        Args:
            primary_llm:   主 LLM 实例
            fallback_llm:  备用 LLM 实例（None 则无 failover，仅重试）
            max_retries:   最大重试次数
            base_delay:    退避基础延迟（秒），实际延迟 = base_delay * (attempt + 1)
        """
        self._primary = primary_llm
        self._fallback = fallback_llm
        self._max_retries = max_retries
        self._base_delay = base_delay
        self._using_fallback = False
        self._failover_count = 0

    # ─── 属性代理 ───
    @property
    def model_name(self):
        return self._primary.model_name

    @property
    def temperature(self):
        return self._primary.temperature

    @property
    def max_tokens(self):
        return self._primary.max_tokens

    def bind_tools(self, tools, **kwargs):
        """代理 bind_tools 到主 LLM（备用 LLM 也绑定同样的 tools）"""
        self._primary = self._primary.bind_tools(tools, **kwargs)
        if self._fallback:
            self._fallback = self._fallback.bind_tools(tools, **kwargs)
        return self

    def with_structured_output(self, model_cls, **kwargs):
        """代理 structured output 到两个 LLM"""
        self._primary = self._primary.with_structured_output(model_cls, **kwargs)
        if self._fallback:
            try:
                self._fallback = self._fallback.with_structured_output(model_cls, **kwargs)
            except Exception:
                pass
        return self

    @property
    def using_fallback(self) -> bool:
        """是否正在使用备用端点"""
        return self._using_fallback

    @property
    def failover_count(self) -> int:
        """故障转移次数"""
        return self._failover_count

    def _should_retry(self, error: Exception) -> bool:
        """判断异常是否应该重试"""
        if not RETRYABLE_EXCEPTIONS:
            return True  # 无法判断时保守重试
        return isinstance(error, RETRYABLE_EXCEPTIONS)

    def _try_invoke(self, llm: ChatOpenAI, messages: list, **kwargs):
        """尝试调用 LLM，返回 (response, error)"""
        try:
            response = llm.invoke(messages, **kwargs)
            return response, None
        except Exception as e:
            return None, e

    def invoke(self, messages: list, **kwargs):
        """
        调用 LLM，带重试 + 故障转移。

        流程:
          1. 主端点调用（带指数退避重试）
          2. 主端点全部失败 → 切换到备用端点
          3. 备用端点也失败 → 抛出异常
        """
        last_error = None

        # ─── 阶段 1: 主端点 + 指数退避 ───
        primary_start = time.time()
        for attempt in range(self._max_retries):
            try:
                result = self._primary.invoke(messages, **kwargs)
                if attempt > 0:
                    logger.info(
                        "[LLM Failover] 主端点第 %d 次重试成功 (总耗时 %.1fs)",
                        attempt + 1, time.time() - primary_start,
                    )
                if self._using_fallback:
                    logger.info("[LLM Failover] 已从备用端点恢复到主端点")
                    self._using_fallback = False
                return result
            except Exception as e:
                last_error = e
                if not self._should_retry(e):
                    logger.warning("[LLM Failover] 不可重试错误，跳过重试: %s", type(e).__name__)
                    break
                if attempt < self._max_retries - 1:
                    delay = self._base_delay * (attempt + 1)
                    logger.warning(
                        "[LLM Failover] 主端点调用失败 (尝试 %d/%d): %s — %.1fs 后重试",
                        attempt + 1, self._max_retries, type(e).__name__, delay,
                    )
                    time.sleep(delay)
                else:
                    logger.error(
                        "[LLM Failover] 主端点 %d 次重试全部失败: %s",
                        self._max_retries, type(e).__name__,
                    )

        # ─── 阶段 2: 切换到备用端点 ───
        if self._fallback and not self._using_fallback:
            logger.warning(
                "[LLM Failover] 切换到备用端点: %s → %s",
                self._primary.model_name, self._fallback.model_name,
            )
            self._using_fallback = True
            self._failover_count += 1
            try:
                result = self._fallback.invoke(messages, **kwargs)
                logger.info("[LLM Failover] 备用端点调用成功")
                return result
            except Exception as e:
                last_error = e
                logger.error("[LLM Failover] 备用端点也失败: %s", type(e).__name__)

        raise last_error or RuntimeError("LLM 调用失败（主备端点均不可用）")

    def stream(self, messages: list, **kwargs):
        """
        流式调用，仅使用当前活跃端点（重试由调用方 ReAct 循环处理）。
        流式场景下重试会导致已发送的 chunk 丢失，因此不做逐 chunk 重试。
        """
        llm = self._fallback if self._using_fallback else self._primary
        try:
            yield from llm.stream(messages, **kwargs)
        except Exception as e:
            if self._fallback and not self._using_fallback and self._should_retry(e):
                logger.warning("[LLM Failover] 流式主端点失败，切换到备用端点: %s", type(e).__name__)
                self._using_fallback = True
                self._failover_count += 1
                try:
                    yield from self._fallback.stream(messages, **kwargs)
                    return
                except Exception as fe:
                    logger.error("[LLM Failover] 流式备用端点也失败: %s", type(fe).__name__)
            raise


def create_llm(
    provider: str = "deepseek",
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    temperature: float = 0.1,
    max_tokens: int = 4096,
    enable_failover: bool = True,
) -> ChatOpenAI | FallbackChatOpenAI:
    """
    创建 LLM 实例

    Args:
        provider:    deepseek / openai / qwen / glm / siliconflow
        model:       模型名，不传则用默认
        base_url:    API 地址，不传则用内置
        api_key:     API Key，不传从环境变量读取
        temperature: 0-1，工具调用建议 < 0.2
        max_tokens:  最大输出 token
        enable_failover: 是否启用双端点故障转移（默认开启）

    Returns:
        ChatOpenAI 或 FallbackChatOpenAI 实例
    """
    p = normalize_provider(provider)

    if p not in PROVIDER_CONFIG:
        raise ValueError(f"不支持的 Provider: {provider}，可用: {list(PROVIDER_CONFIG.keys())}")

    cfg = PROVIDER_CONFIG[p]

    # 优先用传入的 api_key，其次从 Settings（.env），最后从环境变量
    resolved_key = _resolve_api_key(api_key, cfg)

    resolved_model = model or cfg["default_model"]
    resolved_base = base_url or cfg["base_url"]

    logger.info("创建 LLM: provider=%s model=%s T=%.2f", p, resolved_model, temperature)

    primary = ChatOpenAI(
        model=resolved_model,
        base_url=resolved_base,
        api_key=resolved_key,
        temperature=temperature,
        max_tokens=max_tokens,
    )

    # ─── 故障转移 ───
    if not enable_failover:
        return primary

    fallback_url = cfg.get("fallback_url", "")
    fallback_env_key = cfg.get("fallback_env_key", "")
    fallback_model = cfg.get("fallback_model", "")

    if not fallback_url or not fallback_env_key:
        return primary  # 未配置备用端点

    # 解析备用端点的 API Key
    fallback_key = os.getenv(fallback_env_key, "")
    if not fallback_key:
        try:
            from backend.core.config import get_settings
            settings = get_settings()
            fallback_key = getattr(settings, fallback_env_key.lower(), "")
        except Exception:
            pass

    if not fallback_key:
        logger.debug("[LLM Failover] 备用端点 %s 无 API Key，跳过 failover 配置", fallback_env_key)
        return primary

    fallback_llm = ChatOpenAI(
        model=fallback_model or resolved_model,
        base_url=fallback_url,
        api_key=fallback_key,
        temperature=temperature,
        max_tokens=max_tokens,
    )

    logger.info(
        "[LLM Failover] 故障转移已启用: primary=%s@%s, fallback=%s@%s",
        resolved_model, resolved_base,
        fallback_model or resolved_model, fallback_url,
    )

    return FallbackChatOpenAI(
        primary_llm=primary,
        fallback_llm=fallback_llm,
        max_retries=3,
        base_delay=1.0,
    )


def _resolve_api_key(api_key: str | None, cfg: dict) -> str:
    """解析 API Key: 参数 > Settings > 环境变量"""
    if api_key:
        return api_key

    try:
        from backend.core.config import get_settings
        settings = get_settings()
        key = getattr(settings, cfg["env_key"].lower(), "")
        if key:
            return key
    except Exception:
        pass

    key = os.getenv(cfg["env_key"], "")
    if not key:
        raise ValueError(f"未找到 API Key！请设置 {cfg['env_key']}")
    return key


def create_quick_llm(provider: str = "deepseek", enable_failover: bool = True, **kwargs) -> ChatOpenAI | FallbackChatOpenAI:
    """快速思考 LLM — 工具调用型 Agent (SQL/Chart)"""
    return create_llm(provider=provider, temperature=0.1, max_tokens=4096, enable_failover=enable_failover, **kwargs)


def create_deep_llm(provider: str = "deepseek", enable_failover: bool = True, **kwargs) -> ChatOpenAI | FallbackChatOpenAI:
    """深度思考 LLM — 规划和裁判 Agent (Planner/Validator)"""
    return create_llm(provider=provider, temperature=0.3, max_tokens=8192, enable_failover=enable_failover, **kwargs)


# ═══════════════════════════════════════════════
# Token 用量追踪
# ═══════════════════════════════════════════════


class TokenTracker:
    """
    Token 用量追踪器

    每次 LLM 调用后记录输入/输出 token，支持成本分析和用量监控。
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._total_input = 0
        self._total_output = 0
        self._call_count = 0

    def record(self, input_tokens: int = 0, output_tokens: int = 0):
        with self._lock:
            self._total_input += input_tokens
            self._total_output += output_tokens
            self._call_count += 1

    @property
    def total_tokens(self) -> int:
        return self._total_input + self._total_output

    @property
    def call_count(self) -> int:
        return self._call_count

    def snapshot(self) -> dict:
        """获取当前用量快照"""
        with self._lock:
            return {
                "input_tokens": self._total_input,
                "output_tokens": self._total_output,
                "total_tokens": self.total_tokens,
                "call_count": self._call_count,
            }

    def reset(self):
        """重置计数器"""
        with self._lock:
            self._total_input = 0
            self._total_output = 0
            self._call_count = 0


# 全局单例
_token_tracker: TokenTracker | None = None


# 使用 contextvars 替代 global — 支持多租户隔离
_token_tracker_ctx: contextvars.ContextVar = contextvars.ContextVar("token_tracker", default=None)


def get_token_tracker() -> TokenTracker:
    """获取当前上下文的 TokenTracker（contextvars 隔离）"""
    tracker = _token_tracker_ctx.get()
    if tracker is None:
        tracker = TokenTracker()
        _token_tracker_ctx.set(tracker)
    return tracker
