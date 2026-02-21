"""数据层测试"""

from backend.dataflows.sqlite_store import SQLiteStore


class TestSQLiteStore:
    def test_connect(self, temp_db):
        """测试数据库连接"""
        assert temp_db.db_path is not None

    def test_import_csv(self, temp_db, sample_csv):
        """测试 CSV 导入"""
        name = temp_db.import_csv(sample_csv, "sales")
        assert name == "sales"
        assert "sales" in temp_db.get_tables()

    def test_get_tables(self, store_with_data):
        """测试获取表列表"""
        tables = store_with_data.get_tables()
        assert "test_sales" in tables

    def test_get_schema(self, store_with_data):
        """测试获取表结构"""
        schema = store_with_data.get_schema("test_sales")
        cols = [s["name"] for s in schema]
        assert "product" in cols
        assert "amount" in cols
        assert len(schema) == 6

    def test_get_schemas_text(self, store_with_data):
        """测试 schema 文本输出"""
        text = store_with_data.get_schemas_text()
        assert "test_sales" in text
        assert "product" in text

    def test_execute_select(self, store_with_data):
        """测试执行 SELECT"""
        result, error = store_with_data.execute_sql(
            "SELECT COUNT(*) as cnt FROM test_sales"
        )
        assert error == ""
        assert "5" in result

    def test_execute_rejects_insert(self, store_with_data):
        """测试拒绝 INSERT"""
        result, error = store_with_data.execute_sql(
            "INSERT INTO test_sales VALUES (...)"
        )
        assert error != ""
        assert result == ""
        assert "仅允许" in error

    def test_execute_rejects_delete(self, store_with_data):
        """测试拒绝 DELETE"""
        result, error = store_with_data.execute_sql(
            "DELETE FROM test_sales"
        )
        assert error != ""
        assert "仅允许" in error

    def test_preview(self, store_with_data):
        """测试数据预览"""
        preview = store_with_data.preview("test_sales", limit=3)
        assert "product" in preview
        lines = preview.strip().split("\n")
        assert len(lines) <= 4  # header + up to 3 rows

    def test_empty_table(self, temp_db):
        """测试空数据库"""
        assert temp_db.get_tables() == []

    def test_pragma_allowed(self, store_with_data):
        """测试 PRAGMA 可以使用"""
        result, error = store_with_data.execute_sql(
            "PRAGMA table_info('test_sales')"
        )
        assert error == ""
        assert "product" in result

    def test_with_allowed(self, store_with_data):
        """测试 WITH (CTE) 可以使用"""
        result, error = store_with_data.execute_sql(
            "WITH t AS (SELECT * FROM test_sales) SELECT COUNT(*) FROM t"
        )
        assert error == ""
        assert "5" in result

    def test_comment_stripped(self, store_with_data):
        """测试 -- 注释被正确剥离"""
        result, error = store_with_data.execute_sql(
            "-- this is a comment\nSELECT COUNT(*) FROM test_sales"
        )
        assert error == ""
        assert "5" in result
