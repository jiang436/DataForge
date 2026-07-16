"""
文件上传 API

POST /api/upload
  - 接收 CSV 文件
  - 保存到 data/ 目录
  - 导入到 SQLite
  - 返回表结构预览
"""

import logging
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

from backend.tools import get_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["upload"])

UPLOAD_DIR = Path("data")

# 上传限制
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
MAX_ROWS = 100000  # 最多 10 万行


@router.post("/upload")
async def upload_csv(file: UploadFile = File(...)):
    """
    上传 CSV 文件并导入 SQLite

    Args:
        file: CSV 文件（multipart/form-data）

    Returns:
        {
            "table_name": "my_data",
            "columns": [{"name": "date", "type": "TEXT"}, ...],
            "row_count": 500,
            "preview": "date,amount\\n2024-01-01,15000\\n..."
        }
    """
    # ─── 校验文件类型 ───
    if not file.filename or not file.filename.endswith(".csv"):
        raise HTTPException(
            status_code=400,
            detail=f"仅支持 CSV 文件，当前文件: {file.filename}",
        )

    # ─── 校验文件大小 ───
    content = await file.read()
    file_size = len(content)
    if file_size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"文件过大: {file_size / 1024 / 1024:.1f}MB，限制 {MAX_FILE_SIZE / 1024 / 1024:.0f}MB",
        )
    if file_size == 0:
        raise HTTPException(status_code=400, detail="文件为空")

    logger.info("收到文件上传: %s (%.1f KB)", file.filename, file_size / 1024)

    # ─── 保存文件 ───
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    file_path = UPLOAD_DIR / file.filename

    try:
        file_path.write_bytes(content)
        logger.info("文件已保存: %s", file_path)
    except Exception as e:
        logger.error("文件保存失败: %s", e)
        raise HTTPException(status_code=500, detail=f"文件保存失败: {e}") from e

    # ─── 导入 SQLite ───
    try:
        store = get_store()
        table_name = store.import_csv(str(file_path))
        schema = store.get_schema(table_name)

        # 检查行数
        result, error = store.execute_sql(f"SELECT COUNT(*) as cnt FROM '{table_name}'")
        if error:
            raise ValueError(f"查询行数失败: {error}")
        lines = result.split("\n")
        row_count = max(0, len(lines) - 2)  # 减去表头和空行
        if row_count > MAX_ROWS:
            raise HTTPException(
                status_code=413,
                detail=f"数据行数过多: {row_count}，限制 {MAX_ROWS} 行",
            )

        preview = store.preview(table_name, limit=10)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("CSV 导入失败: %s", e)
        raise HTTPException(status_code=500, detail=f"CSV 导入 SQLite 失败: {e}") from e

    logger.info("上传完成: 表=%s, 列数=%d", table_name, len(schema))

    return {
        "table_name": table_name,
        "columns": schema,
        "row_count": max(0, row_count),
        "preview": preview,
    }


@router.get("/tables")
async def list_tables():
    """获取当前数据库中的所有表及其结构"""
    try:
        store = get_store()
        tables = store.get_tables()
        result = {}
        for table_name in tables:
            schema = store.get_schema(table_name)
            preview = store.preview(table_name, limit=5)
            result[table_name] = {
                "columns": schema,
                "preview": preview,
            }
        return result
    except Exception as e:
        logger.error("获取表列表失败: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e
