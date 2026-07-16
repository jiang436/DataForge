"""
报告导出 API

POST /api/export
  - 接收分析结果 → 导出 Markdown / Word / HTML 报告
GET /api/export/formats
  - 列出支持的格式

v3.3: 支持分层报告树导出（format="tree"）
"""

import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from backend.utils.report_exporter import export_report, export_report_tree

logger = logging.getLogger("api")

router = APIRouter(prefix="/api", tags=["export"])


@router.post("/export")
async def export(request: dict):
    """
    导出分析报告

    Request body:
        {
            "format": "docx",        // "md" | "docx" | "html" | "tree"
            "final_report": "...",   // Markdown 报告内容
            "sql_query": "...",      // SQL 查询
            "performance": {...},    // 性能数据
            "validation": "approved",
            "plan": [...],           // 执行计划
            "debate_scores": {...},  // 辩论评分
            ...
        }

    format="tree" 时导出分层报告树（ZIP 下载），其余格式导出单文件。
    """
    fmt = request.get("format", "md")
    if fmt not in ("md", "docx", "html", "tree"):
        raise HTTPException(status_code=400, detail=f"不支持的格式: {fmt}，可选: md, docx, html, tree")

    # 构建 state
    state = {
        "final_report": request.get("final_report", ""),
        "draft_report": request.get("draft_report", ""),
        "sql_query": request.get("sql_query", ""),
        "sql_result": request.get("sql_result", ""),
        "performance_metrics": request.get("performance", {}),
        "validation_result": request.get("validation", "approved"),
        "validation_reason": request.get("validation_reason", ""),
        "user_query": request.get("query", "analysis"),
        "plan": request.get("plan", []),
        "debate_scores": request.get("debate_scores"),
        "optimistic_view": request.get("optimistic_view", ""),
        "pessimistic_view": request.get("pessimistic_view", ""),
        "chart_json": request.get("chart_json"),
        "chart_files": request.get("chart_files", []),
        "available_tables": request.get("tables", []),
    }

    if fmt == "tree":
        root_path = export_report_tree(state)
        # 打包为 ZIP
        import shutil
        import tempfile
        zip_path = str(root_path) + ".zip"
        shutil.make_archive(str(root_path), "zip", root_path)
        return FileResponse(
            path=zip_path,
            media_type="application/zip",
            filename=root_path.name + ".zip",
        )

    filepath = export_report(state, format=fmt)
    if filepath is None:
        raise HTTPException(status_code=500, detail="报告导出失败")

    media_types = {
        "md": "text/markdown",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "html": "text/html",
    }

    return FileResponse(
        path=filepath,
        media_type=media_types.get(fmt, "application/octet-stream"),
        filename=filepath.split("/")[-1],
    )


@router.get("/export/formats")
async def list_formats():
    """列出支持的导出格式"""
    return {
        "formats": [
            {"id": "md", "name": "Markdown", "extension": ".md", "available": True},
            {"id": "docx", "name": "Word 文档", "extension": ".docx", "available": _check_docx()},
            {"id": "html", "name": "HTML", "extension": ".html", "available": True},
            {"id": "tree", "name": "分层报告树 (ZIP)", "extension": ".zip", "available": True},
            {"id": "pdf", "name": "PDF", "extension": ".pdf", "available": _check_pdf()},
        ]
    }


def _check_docx() -> bool:
    try:
        import docx  # noqa
        return True
    except ImportError:
        return False


def _check_pdf() -> bool:
    try:
        import markdown  # noqa
        import weasyprint  # noqa
        return True
    except ImportError:
        return False
