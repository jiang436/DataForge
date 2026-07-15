"""共享 fixtures + 全局配置"""

import os
import tempfile
from pathlib import Path

import pytest

from backend.dataflows.sqlite_store import SQLiteStore
from backend.tools import set_store

# ─── E2E 测试标记 ───


def pytest_addoption(parser):
    parser.addoption(
        "--run-e2e", action="store_true", default=False,
        help="运行 E2E 测试（需真实 LLM API + CSV 数据）",
    )


def pytest_configure(config):
    config.addinivalue_line("markers", "e2e: E2E 测试（需真实 LLM API）")


def pytest_collection_modifyitems(config, items):
    if not config.getoption("--run-e2e"):
        skip_e2e = pytest.mark.skip(reason="需 --run-e2e 参数来运行 E2E 测试")
        for item in items:
            if "e2e" in item.keywords:
                item.add_marker(skip_e2e)


# ─── Fixtures ───


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
