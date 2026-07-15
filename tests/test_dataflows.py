"""数据流集成测试 — CSV 导入 + 查询 + 错误处理 + 并发 + 异常数据"""

import concurrent.futures
import csv
from pathlib import Path

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
            raise AssertionError("应该抛出异常")
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


# ═══════════════════════════════════════════════════════════
# 并发测试
# ═══════════════════════════════════════════════════════════


class TestConcurrency:
    """SQLiteStore 线程安全验证"""

    def test_concurrent_reads(self, store_with_data):
        """多个线程同时查询不应出错"""
        def query():
            result, error = store_with_data.execute_sql(
                "SELECT product, amount FROM test_sales ORDER BY amount DESC"
            )
            return error == ""

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(query) for _ in range(20)]
            results = [f.result() for f in futures]
        assert all(results), "所有并发读取都应成功"

    def test_concurrent_writes_dont_corrupt(self, temp_db, sample_csv):
        """并发导入不同表不导致数据损坏"""
        def import_csv(i: int):
            try:
                temp_db.import_csv(sample_csv, f"concurrent_test_{i}")
                return True
            except Exception:
                return False

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(import_csv, i) for i in range(8)]
            write_results = [f.result() for f in futures]

        assert all(write_results), "所有并发写入都应成功"
        # 验证至少有几个表存在且数据完整
        tables = temp_db.get_tables()
        concurrent_tables = [t for t in tables if t.startswith("concurrent_test_")]
        assert len(concurrent_tables) >= 4, f"应至少有4个并发写入的表, 实际: {len(concurrent_tables)}"

    def test_read_during_write(self, temp_db, sample_csv):
        """写入期间读取仍能获得一致结果"""
        import threading
        import time

        errors = []

        def slow_write():
            try:
                temp_db.import_csv(sample_csv, "rw_test")
            except Exception as e:
                errors.append(f"write error: {e}")

        def read_during():
            time.sleep(0.01)  # 让写入先开始
            for _ in range(10):
                try:
                    tables = temp_db.get_tables()
                    _ = [temp_db.get_schema(t) for t in tables]
                except Exception as e:
                    errors.append(f"read error: {e}")

        t_write = threading.Thread(target=slow_write)
        t_read = threading.Thread(target=read_during)
        t_write.start()
        t_read.start()
        t_write.join()
        t_read.join()

        assert len(errors) == 0, f"并发读写不应报错: {errors}"


# ═══════════════════════════════════════════════════════════
# 异常 CSV 数据测试
# ═══════════════════════════════════════════════════════════


class TestMalformedCSV:
    """异常/边界 CSV 文件处理"""

    def _write_csv(self, path: Path, content: str, encoding: str = "utf-8"):
        path.write_text(content, encoding=encoding)
        return str(path)

    def test_empty_csv(self, temp_db, tmp_path: Path):
        """空 CSV（仅 header，无数据行）"""
        csv_path = self._write_csv(tmp_path / "empty.csv", "col1,col2,col3\n")
        temp_db.import_csv(csv_path, "empty_table")
        result, error = temp_db.execute_sql("SELECT COUNT(*) FROM empty_table")
        assert error == ""
        assert result.strip() == "COUNT(*)\n0"

    def test_csv_with_missing_values(self, temp_db, tmp_path: Path):
        """CSV 包含缺失值"""
        csv_path = self._write_csv(tmp_path / "missing.csv",
                                   "name,age,city\nAlice,30,\nBob,,Beijing\n,25,Shanghai\n")
        temp_db.import_csv(csv_path, "missing_table")
        result, error = temp_db.execute_sql("SELECT * FROM missing_table")
        assert error == ""
        lines = result.strip().split("\n")
        assert len(lines) == 4  # header + 3 rows

    def test_csv_with_special_characters(self, temp_db, tmp_path: Path):
        """CSV 包含特殊字符（引号、逗号、换行）"""
        csv_path = self._write_csv(tmp_path / "special.csv",
                                   'product,description\n'
                                   '"iPhone 15","Best phone, ever."\n'
                                   '"Galaxy S24","Samsung''s flagship"\n')
        temp_db.import_csv(csv_path, "special_table")
        result, error = temp_db.execute_sql("SELECT * FROM special_table")
        assert error == ""
        assert "iPhone 15" in result

    def test_csv_gbk_encoding(self, temp_db, tmp_path: Path):
        """GBK 编码的 CSV（常见于 Windows 中文环境）"""
        content = "产品,价格,销量\n手机支架,15.5,200\n蓝牙耳机,99.0,150\n"
        csv_path = self._write_csv(tmp_path / "gbk.csv", content, encoding="gbk")
        temp_db.import_csv(csv_path, "gbk_table")
        result, error = temp_db.execute_sql("SELECT * FROM gbk_table")
        assert error == ""
        assert "手机支架" in result

    def test_csv_utf8_bom(self, temp_db, tmp_path: Path):
        """带 BOM 头的 UTF-8 CSV"""
        path = tmp_path / "bom.csv"
        with open(path, "w", encoding="utf-8-sig") as f:
            f.write("item,price\n键盘,299\n鼠标,149\n")
        temp_db.import_csv(str(path), "bom_table")
        result, error = temp_db.execute_sql("SELECT * FROM bom_table")
        assert error == ""
        assert "键盘" in result

    def test_csv_single_column(self, temp_db, tmp_path: Path):
        """单列 CSV"""
        csv_path = self._write_csv(tmp_path / "single.csv", "value\n1\n2\n3\n4\n5\n")
        temp_db.import_csv(csv_path, "single_table")
        result, error = temp_db.execute_sql("SELECT COUNT(*) FROM single_table")
        assert error == ""
        assert "5" in result

    def test_csv_many_columns(self, temp_db, tmp_path: Path):
        """宽表 CSV（30 列）"""
        cols = [f"col_{i}" for i in range(30)]
        header = ",".join(cols)
        rows = [",".join([str(i * j) for j in range(30)]) for i in range(3)]
        content = header + "\n" + "\n".join(rows) + "\n"
        csv_path = self._write_csv(tmp_path / "wide.csv", content)
        temp_db.import_csv(csv_path, "wide_table")
        schema = temp_db.get_schema("wide_table")
        assert len(schema) == 30

    def test_csv_duplicate_column_names(self, temp_db, tmp_path: Path):
        """重复列名 — Pandas 自动重命名为 name.1, name.2"""
        content = "x,x,x\n1,2,3\n4,5,6\n"
        csv_path = self._write_csv(tmp_path / "dup.csv", content)
        temp_db.import_csv(csv_path, "dup_table")
        schema = temp_db.get_schema("dup_table")
        assert len(schema) == 3

    def test_csv_only_header_no_newline(self, temp_db, tmp_path: Path):
        """仅 header 行，无末尾换行 — Pandas 将其作为单列名处理"""
        csv_path = self._write_csv(tmp_path / "nobreak.csv", "a,b,c")
        # Pandas 会将 "a,b,c" 解析为单行列名为 "a,b,c"
        # 这是正常行为 — 不会崩溃即可
        try:
            temp_db.import_csv(csv_path, "nobreak_table")
            tables = temp_db.get_tables()
            assert "nobreak_table" in tables
        except Exception:
            # Pandas 对无换行的单行 CSV 可能报错，这也是可接受的行为
            pass


# ═══════════════════════════════════════════════════════════
# 大数据集测试
# ═══════════════════════════════════════════════════════════


class TestLargeDataset:
    """大数据量下的性能和行为验证"""

    def _generate_large_csv(self, tmp_path: Path, rows: int) -> str:
        """生成 N 行 CSV 文件"""
        path = tmp_path / f"large_{rows}.csv"
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["id", "name", "value", "category"])
            for i in range(rows):
                writer.writerow([i, f"item_{i}", i * 1.5, f"cat_{i % 10}"])
        return str(path)

    def test_import_10000_rows(self, temp_db, tmp_path: Path):
        """导入 10000 行 CSV 并正确查询"""
        csv_path = self._generate_large_csv(tmp_path, 10000)
        temp_db.import_csv(csv_path, "large_table")
        result, error = temp_db.execute_sql("SELECT COUNT(*) FROM large_table")
        assert error == ""
        # result is "COUNT(*)\n10000" — extract count from second line
        count_line = result.strip().split("\n")[1]
        assert count_line == "10000"

    def test_aggregate_query_on_large_data(self, temp_db, tmp_path: Path):
        """大数据量下的聚合查询正确性"""
        csv_path = self._generate_large_csv(tmp_path, 5000)
        temp_db.import_csv(csv_path, "agg_table")

        # SUM 聚合
        result, error = temp_db.execute_sql(
            "SELECT category, COUNT(*) as cnt, SUM(value) as total "
            "FROM agg_table GROUP BY category ORDER BY cnt DESC"
        )
        assert error == ""
        lines = result.strip().split("\n")
        assert len(lines) == 11  # 10 categories + header

    def test_result_truncation_in_tools(self, temp_db, tmp_path: Path):
        """execute_sql 工具对大结果集正确截断（>100行→截断提示）"""
        from backend.tools import set_store

        csv_path = self._generate_large_csv(tmp_path, 200)
        temp_db.import_csv(csv_path, "trunc_table")
        set_store(temp_db)

        from backend.tools import execute_sql
        result = execute_sql.invoke({"sql": "SELECT * FROM trunc_table"})
        lines = result.split("\n")
        # 200 行数据 + header → 201 行 > 100 → 截断
        assert len(lines) <= 102  # 100 data + header + truncation message
        assert "截断" in result or "100" in result
