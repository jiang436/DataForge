"""
全局错误处理中间件


统一捕获异常，按类型返回标准化 JSON 错误响应。
支持 AgentFin 类型化异常体系，按异常类型映射 HTTP 状态码。
"""

import logging
import traceback

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from backend.core.errors import AgentFinError, ERROR_STATUS_MAP

logger = logging.getLogger("api")


class ErrorHandlerMiddleware(BaseHTTPMiddleware):
    """全局错误处理，所有未捕获异常统一格式化"""

    async def dispatch(self, request: Request, call_next) -> Response:
        try:
            return await call_next(request)
        except Exception as exc:
            return self._handle(request, exc)

    def _handle(self, request: Request, exc: Exception) -> JSONResponse:
        request_id = getattr(request.state, "request_id", "-")
        path = request.url.path

        logger.error(
            "请求异常 [%s] %s %s: %s",
            request_id,
            request.method,
            path,
            str(exc),
        )
        logger.debug("异常详情: %s", traceback.format_exc())

        # ─── AgentFin 类型化异常 ───
        if isinstance(exc, AgentFinError):
            status = ERROR_STATUS_MAP.get(type(exc), 500)
            code = type(exc).__name__.replace("Error", "").upper()
            return JSONResponse(
                status_code=status,
                content={
                    "error": {
                        "code": code,
                        "message": str(exc),
                        "detail": exc.detail,
                    }
                },
            )

        # ─── 标准 Python 异常 ───
        if isinstance(exc, ValueError):
            return JSONResponse(
                status_code=400,
                content={"error": {"code": "VALIDATION_ERROR", "message": str(exc)}},
            )
        if isinstance(exc, PermissionError):
            return JSONResponse(
                status_code=403, content={"error": {"code": "FORBIDDEN", "message": "权限不足"}}
            )
        if isinstance(exc, FileNotFoundError):
            return JSONResponse(
                status_code=404, content={"error": {"code": "NOT_FOUND", "message": str(exc)}}
            )

        # 未知异常
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "INTERNAL_ERROR", "message": "服务器内部错误"}},
        )
