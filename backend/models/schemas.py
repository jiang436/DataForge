"""
API 请求/响应模型

Pydantic v2 模型，FastAPI 自动生成 Swagger 文档。
"""

from pydantic import BaseModel, Field

# ─── 请求模型 ───


class ChatRequest(BaseModel):
    """分析对话请求"""

    query: str = Field(..., description="数据分析问题", min_length=1, max_length=2000)
    tables: list[str] = Field(default_factory=list, description="要查询的表名列表")


# ─── 响应模型 ───


class TableInfo(BaseModel):
    """数据表信息"""

    table_name: str = Field(..., description="表名")
    columns: list[dict] = Field(default_factory=list, description="列信息")
    row_count: int = Field(default=0, description="行数")
    preview: str = Field(default="", description="前10行预览")


class UploadResponse(BaseModel):
    """CSV 上传响应"""

    table_name: str
    columns: list[dict]
    row_count: int
    preview: str


class PerformanceMetrics(BaseModel):
    """性能统计"""

    total_time: float = Field(default=0, description="总耗时(秒)")
    node_count: int = Field(default=0, description="执行节点数")
    average_node_time: float = Field(default=0, description="平均节点耗时(秒)")
    slowest_node: dict | None = None
    fastest_node: dict | None = None
    node_timings: dict = Field(default_factory=dict)


class AnalysisResult(BaseModel):
    """分析结果"""

    final_report: str = Field(default="", description="Markdown 分析报告")
    performance: PerformanceMetrics | None = None
    validation_result: str = Field(default="", description="裁判结果: approved/rejected")
    validation_reason: str = Field(default="", description="裁判理由")


class ChatResponse(BaseModel):
    """对话响应（SSE 逐条推送的汇总）"""

    status: str = Field(default="ok")
    result: AnalysisResult | None = None


class HealthResponse(BaseModel):
    """健康检查响应"""

    status: str
    tables: list[str] = Field(default_factory=list)
    tables_count: int = 0
    message: str | None = None
