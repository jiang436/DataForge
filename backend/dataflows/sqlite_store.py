"""
SQLite 数据存储层

负责:
  1. 动态创建 SQLite 数据库和表
  2. CSV 文件导入为 SQLite 表
  3. 查询表结构和数据预览
  4. 执行 SQL（只读查询）

设计决策:
  - 使用 SQLite 而非 PostgreSQL/MySQL：零配置，面试现场一键启动
  - 仅允许 SELECT 语句：防止 Agent 误操作修改数据
  - 每个分析会话使用独立数据库文件，避免数据污染
"""

import logging
import re
import sqlite3
import threading
from pathlib import Path

import pandas as pd


def _sanitize_column_name(name: str) -> str:
    """
    清理列名中的特殊字符，使其安全用于 SQL。

    规则:
      - 去掉中文括号及其内容: 价格（元）→ 价格, 好评率（%）→ 好评率
      - 去掉 % 符号
      - 多余空格/下划线合并为单个下划线
      - 去掉首尾空格和下划线
    """
    # 去掉中文括号及其内的单位/说明: （元）, （件）, （%）, （月）
    name = re.sub(r"[（(][^）)]*[）)]", "", name)
    # 去掉残留的 % 符号
    name = name.replace("%", "")
    # 多个空白/_合并
    name = re.sub(r"[\s_]+", "_", name)
    # 去掉首尾的 _ 和空格
    name = name.strip(" _")
    return name

logger = logging.getLogger(__name__)


class SQLiteStore:
    """SQLite 数据库管理器（线程安全）"""

    def __init__(self, db_path: str = ":memory:"):
        """
        Args:
            db_path: 数据库路径。默认 :memory: 使用内存数据库；
                     可指定文件路径做持久化
        """
        self.db_path = db_path
        self._lock = threading.Lock()
        # check_same_thread=False: FastAPI 异步环境下允许多线程访问
        # 配合 threading.Lock 保证线程安全
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row  # 查询结果可通过列名访问
        # 启用 WAL 模式：写不阻塞读，大幅提升并发性能
        self.conn.execute("PRAGMA journal_mode=WAL")
        # 并发友好设置
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute("PRAGMA busy_timeout=5000")
        logger.info("SQLite 数据库已连接: %s (WAL 模式, 线程安全)", db_path)

    def import_csv(self, csv_path: str, table_name: str | None = None) -> str:
        """
        将 CSV 文件导入为 SQLite 表

        实现细节:
          先用 Pandas 读取 CSV（自动处理编码、缺失值），
          再通过 df.to_sql() 写入 SQLite（自动推断列类型）。

        Args:
            csv_path:   CSV 文件路径
            table_name: 表名，不传则使用文件名（去除扩展名）

        Returns:
            创建的表名
        """
        file_path = Path(csv_path)
        if not file_path.exists():
            raise FileNotFoundError(f"CSV 文件不存在: {csv_path}")

        if table_name is None:
            table_name = file_path.stem.replace("-", "_").replace(" ", "_")

        logger.info("导入CSV: %s → 表名: %s", csv_path, table_name)

        # Pandas 读取 CSV（自动处理编码问题）
        try:
            df = pd.read_csv(csv_path, encoding="utf-8")
        except UnicodeDecodeError:
            logger.warning("UTF-8 读取失败，尝试 GBK 编码")
            df = pd.read_csv(csv_path, encoding="gbk")

        # 清理列名：去掉特殊字符（好评率（%）→ 好评率，价格（元）→ 价格）
        original_cols = list(df.columns)
        df.columns = [_sanitize_column_name(c) for c in df.columns]
        renamed = [(o, n) for o, n in zip(original_cols, df.columns) if o != n]
        if renamed:
            logger.info("列名清理: %s", renamed)

        # 如果表已存在则替换（会话级别，每次导入是最新数据）
        with self._lock:
            df.to_sql(table_name, self.conn, if_exists="replace", index=False)

        row_count = len(df)
        col_count = len(df.columns)
        logger.info("导入完成: %s (%d 行 × %d 列)", table_name, row_count, col_count)

        return table_name

    def get_tables(self) -> list[str]:
        """获取数据库中所有表名"""
        cursor = self.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        return [row[0] for row in cursor.fetchall()]

    def get_schema(self, table_name: str) -> list[dict]:
        """
        获取表结构

        Returns:
            [{"name": "date", "type": "TEXT"}, {"name": "amount", "type": "REAL"}, ...]
        """
        cursor = self.conn.execute(f"PRAGMA table_info('{table_name}')")
        return [{"name": row[1], "type": row[2]} for row in cursor.fetchall()]

    def get_schemas_text(self) -> str:
        """
        获取所有表的 schema 文本，注入到 Agent prompt 中

        Returns:
            Table: sales
            Columns: date(TEXT), product(TEXT), amount(REAL), ...

            Table: orders
            Columns: ...
        """
        lines = []
        for table_name in self.get_tables():
            schema = self.get_schema(table_name)
            cols = ", ".join(f"{s['name']}({s['type']})" for s in schema)
            lines.append(f"Table: {table_name}\nColumns: {cols}\n")
        return "\n".join(lines)

    def preview(self, table_name: str, limit: int = 5) -> str:
        """
        预览表数据（前 N 行），用于前端展示

        Returns:
            CSV 格式的文本
        """
        cursor = self.conn.execute(f"SELECT * FROM '{table_name}' LIMIT {limit}")
        rows = cursor.fetchall()
        if not rows:
            return "(空表)"

        columns = [desc[0] for desc in cursor.description]
        result = ",".join(columns) + "\n"
        for row in rows:
            result += ",".join(str(v) for v in row) + "\n"
        return result

    def execute_sql(self, sql: str) -> tuple[str, str]:
        """
        执行 SELECT 查询

        安全措施:
          - 仅允许 SELECT 语句
          - 禁止 INSERT/UPDATE/DELETE/DROP/ALTER/CREATE

        Args:
            sql: SELECT 语句

        Returns:
            (csv_result, error)
            - 成功: (CSV格式查询结果, "")
            - 失败: ("", 错误信息)
        """
        import sqlparse

        # ─── AST 级别安全检查 ───
        # sqlparse 正确解析 SQL 语法树，不受注释/Unicode/大小写混淆绕过
        try:
            statements = sqlparse.parse(sql)
        except Exception as e:
            return "", f"SQL 解析失败: {e}"

        if not statements:
            return "", "安全限制：未检测到有效的 SQL 语句"

        allowed_types = {"SELECT", "PRAGMA", "EXPLAIN", "WITH"}
        forbidden_keywords = {"INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE",
                              "ATTACH", "DETACH", "REINDEX", "VACUUM", "GRANT", "REVOKE"}

        for stmt in statements:
            if stmt.get_type() == "UNKNOWN":
                tokens = [t for t in stmt.flatten() if not t.is_whitespace]
                first_keyword = tokens[0].value.upper() if tokens else ""
                if first_keyword not in allowed_types:
                    return "", (
                        f"安全限制：无法识别的语句类型 '{first_keyword}'。"
                        f"仅允许: {', '.join(sorted(allowed_types))}"
                    )
            elif stmt.get_type() not in allowed_types:
                return "", (
                    f"安全限制：禁止 {stmt.get_type()} 操作。"
                    f"仅允许: {', '.join(sorted(allowed_types))}"
                )
            for token in stmt.flatten():
                if token.ttype is sqlparse.tokens.Keyword and token.value.upper() in forbidden_keywords:
                    return "", f"安全限制：禁止 {token.value.upper()} 操作"

        # ─── 执行查询 ───
        logger.info("执行 SQL: %s", sql[:200])
        try:
            with self._lock:
                cursor = self.conn.execute(sql)
                rows = cursor.fetchall()

            if not rows:
                return "(查询成功，但无返回数据)", ""

            # 转换为 CSV 文本
            columns = [desc[0] for desc in cursor.description]
            result_lines = [",".join(columns)]
            for row in rows:
                result_lines.append(",".join(str(v) for v in row))

            result = "\n".join(result_lines)
            logger.info("查询返回 %d 行 × %d 列", len(rows), len(columns))
            return result, ""

        except Exception as e:
            error_msg = str(e)
            logger.error("SQL 执行失败: %s", error_msg)
            return "", error_msg

    def close(self):
        """关闭数据库连接"""
        self.conn.close()
        logger.info("SQLite 数据库已关闭")
