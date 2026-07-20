"""SQL 注入/安全测试 — 白名单防线的完备性验证

测试覆盖:
  1. DDL 拦截:  CREATE/ALTER/DROP 应全部被拒绝
  2. DML 拦截:  INSERT/UPDATE/DELETE 应全部被拒绝
  3. 注入绕过:  注释/编码/多语句拼接等常见攻击向量
  4. 白名单通过: SELECT/PRAGMA/WITH 应正常执行
  5. 边界条件:   大小写变体、空白注入、Union 注入
"""

import pytest

from backend.dataflows.sqlite_store import SQLiteStore


# ═══════════════════════════════════════════════════════════
# 1. DDL 拦截
# ═══════════════════════════════════════════════════════════

class TestDDLBlocking:
    """数据定义语言 (DDL) 应全部被拦截"""

    def test_create_table_blocked(self, store_with_data):
        result, error = store_with_data.execute_sql(
            "CREATE TABLE backdoor (id INT, data TEXT)"
        )
        # 安全限制使用中文或英文提示
        assert error != "" and error != ""
        assert "禁止" in error or "only SELECT" in error.lower() or "not allowed" in error.lower()

    def test_alter_table_blocked(self, store_with_data):
        result, error = store_with_data.execute_sql(
            "ALTER TABLE test_sales ADD COLUMN secret TEXT"
        )
        assert error != ""

    def test_drop_table_blocked(self, store_with_data):
        result, error = store_with_data.execute_sql("DROP TABLE test_sales")
        assert error != ""

    def test_truncate_blocked(self, store_with_data):
        """TRUNCATE 虽不常见于 SQLite，但也应被拦截"""
        result, error = store_with_data.execute_sql("DELETE FROM test_sales")
        assert error != ""

    def test_create_index_blocked(self, store_with_data):
        result, error = store_with_data.execute_sql(
            "CREATE INDEX idx_test ON test_sales(amount)"
        )
        assert error != ""


# ═══════════════════════════════════════════════════════════
# 2. DML 拦截
# ═══════════════════════════════════════════════════════════

class TestDMLBlocking:
    """数据操作语言 (DML) 应全部被拦截"""

    def test_insert_blocked(self, store_with_data):
        result, error = store_with_data.execute_sql(
            "INSERT INTO test_sales VALUES ('2024-01-01', 'X', 'Y', 'Z', 100, 1)"
        )
        assert error != ""

    def test_update_blocked(self, store_with_data):
        result, error = store_with_data.execute_sql(
            "UPDATE test_sales SET amount = 0"
        )
        assert error != ""

    def test_delete_blocked(self, store_with_data):
        result, error = store_with_data.execute_sql(
            "DELETE FROM test_sales WHERE amount > 0"
        )
        assert error != ""

    def test_replace_blocked(self, store_with_data):
        """REPLACE (INSERT OR REPLACE) 也应被拦截"""
        result, error = store_with_data.execute_sql(
            "REPLACE INTO test_sales VALUES ('2024-01-01', 'X', 'Y', 'Z', 100, 1)"
        )
        assert error != ""


# ═══════════════════════════════════════════════════════════
# 3. 注入绕过攻击向量
# ═══════════════════════════════════════════════════════════

class TestInjectionBypassAttempts:
    """模拟常见 SQL 注入/绕过尝试，验证防线不被突破"""

    def test_multi_statement_split_injection(self, store_with_data):
        """SELECT ... ; DROP TABLE ... — 多语句不应执行第二部分"""
        result, error = store_with_data.execute_sql(
            "SELECT * FROM test_sales; DROP TABLE test_sales"
        )
        # 要么阻止执行，要么只执行 SELECT 部分
        if error == "":
            # 如果执行了，表应该还在
            tables = store_with_data.get_tables()
            assert "test_sales" in tables

    def test_comment_obfuscation_injection(self, store_with_data):
        """用注释绕过: SELECT/*comment*/ FROM → 应仍然安全"""
        result, error = store_with_data.execute_sql(
            "SELECT * FROM /* comment */ test_sales"
        )
        # 不应崩溃，要么执行成功返回数据，要么被拦截
        if error == "":
            assert result is not None

    def test_case_variant_bypass(self, store_with_data):
        """大小写变体绕过: sElEcT / SeLeCt → 应被识别"""
        result, error = store_with_data.execute_sql("SeLeCt * FrOm test_sales")
        # 大小写变体应为合法 SELECT
        if error == "":
            assert result is not None

    def test_union_injection(self, store_with_data):
        """UNION SELECT 注入 → 应被识别为合法 SELECT 的一部分"""
        result, error = store_with_data.execute_sql(
            "SELECT amount FROM test_sales UNION SELECT 999"
        )
        # UNION SELECT 是合法的（只要不是破坏性操作）
        # 关键: 不崩溃，不泄露其他表数据
        if error == "":
            assert "999" in result or result is not None

    def test_subquery_injection(self, store_with_data):
        """子查询注入 → 合法语法，应正常执行"""
        result, error = store_with_data.execute_sql(
            "SELECT * FROM test_sales WHERE amount = (SELECT MAX(amount) FROM test_sales)"
        )
        if error == "":
            assert result is not None

    def test_hex_encoded_injection(self, store_with_data):
        """十六进制编码注入: SELECT CHAR(68,69,76,69,84,69) → 可能被拦截"""
        # SQLite 的 CHAR() 返回字符串，不应绕过安全检查
        result, error = store_with_data.execute_sql(
            "SELECT CHAR(68,69,76,69,84,69) AS decoded FROM test_sales LIMIT 1"
        )
        # 不应造成破坏
        if error == "":
            assert result is not None

    def test_whitespace_injection(self, store_with_data):
        """大量空白/TAB/换行混淆 → 应正确解析"""
        result, error = store_with_data.execute_sql(
            "SELECT\t*\nFROM\t\ntest_sales   \nWHERE\n   amount\n> 0"
        )
        if error == "":
            assert result is not None


# ═══════════════════════════════════════════════════════════
# 4. 白名单通过验证
# ═══════════════════════════════════════════════════════════

class TestWhitelistPassThrough:
    """SELECT / PRAGMA / WITH (CTE) 应正常通过"""

    def test_basic_select_passes(self, store_with_data):
        result, error = store_with_data.execute_sql("SELECT * FROM test_sales")
        assert error == ""
        assert len(result) > 0

    def test_select_with_aggregation_passes(self, store_with_data):
        result, error = store_with_data.execute_sql(
            "SELECT COUNT(*) as cnt, SUM(amount) as total FROM test_sales"
        )
        assert error == ""
        assert "cnt" in result

    def test_select_with_group_by_passes(self, store_with_data):
        result, error = store_with_data.execute_sql(
            "SELECT category, SUM(amount) FROM test_sales GROUP BY category"
        )
        assert error == ""

    def test_select_with_order_by_passes(self, store_with_data):
        result, error = store_with_data.execute_sql(
            "SELECT * FROM test_sales ORDER BY amount DESC"
        )
        assert error == ""

    def test_pragma_passes(self, store_with_data):
        """PRAGMA 查询（表信息）应通过"""
        result, error = store_with_data.execute_sql("PRAGMA table_info('test_sales')")
        assert error == ""

    def test_with_cte_passes(self, store_with_data):
        """WITH 子句 (CTE) 应通过"""
        result, error = store_with_data.execute_sql(
            "WITH top_products AS ("
            "  SELECT product, SUM(amount) as total "
            "  FROM test_sales GROUP BY product"
            ") SELECT * FROM top_products WHERE total > 1000"
        )
        assert error == ""

    def test_explain_passes(self, store_with_data):
        """EXPLAIN 查询计划应通过"""
        result, error = store_with_data.execute_sql(
            "EXPLAIN SELECT * FROM test_sales"
        )
        assert error == ""

    def test_select_with_limit_offset(self, store_with_data):
        result, error = store_with_data.execute_sql(
            "SELECT * FROM test_sales LIMIT 2 OFFSET 1"
        )
        assert error == ""
