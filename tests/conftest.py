"""共享 fixtures"""

import os
import tempfile
from pathlib import Path

import pytest

from backend.dataflows.sqlite_store import SQLiteStore
from backend.tools import set_store


@pytest.fixture
def temp_db():
    """临时 SQLite 数据库"""
    db_path = os.path.join(tempfile.gettempdir(), "test_dataforge.db")
    store = SQLiteStore(db_path=db_path)
    set_store(store)
    yield store
    store.close()
    try:
        os.remove(db_path)
    except OSError:
        pass


@pytest.fixture
def sample_csv(tmp_path: Path):
    """生成示例 CSV 文件"""
    csv_path = tmp_path / "test_sales.csv"
    csv_path.write_text(
        "date,product,category,region,amount,quantity\n"
        "2024-01-15,手机支架,3C配件,华东,15000,200\n"
        "2024-02-20,蓝牙耳机,音频,华南,28000,150\n"
        "2024-03-10,充电宝,充电续航,华北,12000,300\n"
        "2024-04-05,数据线,线材,华东,8000,500\n"
        "2024-05-18,手机壳,保护壳,华南,18000,400\n",
        encoding="utf-8",
    )
    return str(csv_path)


@pytest.fixture
def store_with_data(temp_db, sample_csv):
    """带示例数据的 SQLite store"""
    temp_db.import_csv(sample_csv, table_name="test_sales")
    return temp_db
