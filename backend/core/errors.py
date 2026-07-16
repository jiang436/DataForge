"""
AgentFin 异常层次 — 为每种故障模式提供类型化异常。

每个异常携带可选的 detail dict 用于结构化错误报告。
ErrorHandlerMiddleware 按异常类型映射到合适的 HTTP 状态码。

参考: tradingagents/dataflows/errors.py → VendorError 体系
"""


class AgentFinError(Exception):
    """所有 AgentFin 异常的基类。"""

    def __init__(self, message: str, detail: dict | None = None):
        self.detail = detail or {}
        super().__init__(message)


class LLMError(AgentFinError):
    """LLM 调用失败（连接、限流、超时、响应异常）。

    HTTP 502 Bad Gateway — 上游 LLM 服务故障。
    """

    def __init__(
        self,
        message: str,
        provider: str = "",
        model: str = "",
        detail: dict | None = None,
    ):
        self.provider = provider
        self.model = model
        super().__init__(message, detail)


class SQLError(AgentFinError):
    """SQL 执行失败（语法错误、表不存在、权限不足）。

    HTTP 422 Unprocessable Entity。
    """

    def __init__(self, message: str, sql: str = "", detail: dict | None = None):
        self.sql = sql
        super().__init__(message, detail)


class ChartError(AgentFinError):
    """图表生成失败（无效数据、渲染异常）。

    HTTP 422 Unprocessable Entity。
    """

    def __init__(self, message: str, chart_type: str = "", detail: dict | None = None):
        self.chart_type = chart_type
        super().__init__(message, detail)


class ValidationError(AgentFinError):
    """验证失败（数据不一致、逻辑错误）。

    HTTP 400 Bad Request。
    """

    ...


class ConfigError(AgentFinError):
    """配置错误（缺少 API Key、无效设置）。

    HTTP 500 Internal Server Error。
    """

    ...


# ─── HTTP 状态码映射 ───

ERROR_STATUS_MAP: dict[type[AgentFinError], int] = {
    ConfigError: 500,
    LLMError: 502,       # Bad Gateway — 上游 LLM 故障
    SQLError: 422,       # Unprocessable Entity
    ChartError: 422,
    ValidationError: 400,
}
