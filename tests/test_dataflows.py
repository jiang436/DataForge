"""数据流集成测试 — CSV 导入 + 查询 + 错误处理"""

from backend.dataflows.sqlite_store import SQLiteStore


class TestCSVImport:
    def test_import_and_query(self, store_with_data):
        """导入 CSV 后查询数据正确"""
        result, error = store_with_data.execute_sql(
            "SELECT product, amount FROM test_sales ORDER BY amount DESC"
        )
        assert error == ""
        lines = result.strip().split("\n")
        assert len(lines) == 6  # header + 5 rows
        assert "蓝牙耳机" in lines[1]  # highest amount

    def test_import_nonexistent_file(self):
        """导入不存在的文件抛出异常"""
        store = SQLiteStore()
        try:
            store.import_csv("nonexistent.csv")
            assert False, "应该抛出异常"
        except FileNotFoundError:
            pass

    def test_multiple_imports(self, temp_db, sample_csv):
        """多次导入覆盖旧表"""
        temp_db.import_csv(sample_csv, "test")
        count1, _ = temp_db.execute_sql("SELECT COUNT(*) FROM test")
        temp_db.import_csv(sample_csv, "test")
        count2, _ = temp_db.execute_sql("SELECT COUNT(*) FROM test")
        assert count1 == count2  # 覆盖，行数不变


class TestSQLErrorHandling:
    def test_syntax_error(self, store_with_data):
        """SQL 语法错误返回错误信息"""
        result, error = store_with_data.execute_sql(
            "SELECTT * FROM test_sales"
        )
        assert error != ""
        assert result == ""

    def test_table_not_found(self, store_with_data):
        """查询不存在的表"""
        result, error = store_with_data.execute_sql(
            "SELECT * FROM nonexistent"
        )
        assert error != ""

    def test_column_not_found(self, store_with_data):
        """查询不存在的列"""
        result, error = store_with_data.execute_sql(
            "SELECT fake_column FROM test_sales"
        )
        assert error != ""
