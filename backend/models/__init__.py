"""
Pydantic 数据模型

参考: tradingagents/models/stock_data_models.py

FastAPI 自动根据 Pydantic 模型生成 OpenAPI 文档 (Swagger UI)。
"""

from backend.models.schemas import (
    AnalysisResult,
    ChatRequest,
    ChatResponse,
    HealthResponse,
    PerformanceMetrics,
    TableInfo,
    UploadResponse,
)

__all__ = [
    "ChatRequest",
    "ChatResponse",
    "UploadResponse",
    "TableInfo",
    "AnalysisResult",
    "PerformanceMetrics",
    "HealthResponse",
]
