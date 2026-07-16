"""
数据层 — SQLite 存储 + 演示数据生成

参考: tradingagents/dataflows/ 模式

用法:
    from backend.dataflows import SQLiteStore, generate_all
"""

from backend.dataflows.demo_data import (
    generate_all,
    generate_orders,
    generate_sales,
    generate_users,
)
from backend.dataflows.sqlite_store import SQLiteStore

__all__ = [
    "SQLiteStore",
    "generate_all",
    "generate_sales",
    "generate_orders",
    "generate_users",
]
