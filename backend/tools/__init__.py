"""
Agent 工具函数

LangChain 的 @tool 装饰器将 Python 函数注册为 LLM 可调用的 Tool。
Agent 判断需要工具时会输出 tool_call，ReAct 循环内自动执行并返回结果。

参考: tradingagents/agents/utils/agent_utils.py → Toolkit 类中的 @tool 方法

工具清单:
  - get_table_info:      查看指定表的结构（列名、类型、示例数据）
  - execute_sql:         执行 SELECT 查询
  - validate_sql:        校验 SQL 语法（不实际执行）
  - generate_chart:      根据数据生成 Plotly 图表 JSON（快速路径）
  - execute_python_code: 执行自定义 matplotlib/plotly Python 代码（高质量路径）

依赖注入:
  LangChain 的 @tool 装饰器要求工具函数签名清洁（供 LLM 理解），无法通过函数
  参数注入依赖。因此使用模块级 _store + set_store() 模式。这不是全局状态滥用，
  而是 LangChain 生态中 Tool 的标准依赖注入方式（类似 Flask 的 g / Django 的
  thread-local）。生产环境中可扩展为 contextvars 版本支持多租户。

测试隔离:
  set_store(mock) → 测试 → reset_store() 确保测试间不相互污染。

使用方式:
    from backend.tools import set_store, create_tools
    set_store(my_store_instance)
    tools = create_tools()  # 返回 {sql_tools, chart_tools, all_tools}
"""

import json
import logging

from langchain_core.tools import tool

from backend.utils.tool_logging import log_tool_call

logger = logging.getLogger(__name__)

# ─── Store 依赖注入 ───
# LangChain @tool 函数签名必须清洁（供 LLM 理解参数语义），
# 因此通过 contextvars 注入 store 引用而非函数参数。
# contextvars 天然支持 async 多租户隔离，优于 global。

_store: object = None


def set_store(store):
    """注入 SQLiteStore 实例（应用启动时或测试前调用）"""
    global _store
    _store = store
    logger.debug("SQLiteStore 已注入")


def get_store():
    """获取 SQLiteStore 实例"""
    if _store is None:
        raise RuntimeError("SQLiteStore 未初始化，请先调用 set_store()")
    return _store


def reset_store():
    """重置 store（测试隔离用）"""
    global _store
    _store = None
    logger.debug("SQLiteStore 已重置")


# ═══════════════════════════════════════════════════════════
# SQL 相关工具
# ═══════════════════════════════════════════════════════════


@tool
@log_tool_call(tool_name="get_table_info")
def get_table_info(table_name: str = "") -> str:
    """
    查看指定表的结构信息：列名、数据类型、前3行示例数据。

    何时调用:
      - 开始编写 SQL 之前，先确认表中有哪些列
      - 不确定列名拼写时
      - 需要了解数据类型时（数字 vs 文本）

    Args:
        table_name: 表名。如果不确定表名，传入空字符串查看所有可用表。

    Returns:
        表结构文本 + 前3行数据预览
    """
    logger.info("[Tool] get_table_info: table_name='%s'", table_name)

    store = get_store()

    # 空字符串或不传 → 列出所有可用表
    if not table_name or not table_name.strip():
        tables = store.get_tables()
        if not tables:
            return "没有可用的数据表。请先上传 CSV 文件。"
        lines = ["## 可用数据表\n"]
        for t in tables:
            schema = store.get_schema(t)
            cols = ", ".join(f"{c['name']}({c['type']})" for c in schema)
            lines.append(f"- **{t}**: {cols}")
        return "\n".join(lines)

    try:
        schema = store.get_schema(table_name)
        if not schema:
            return f"表 '{table_name}' 不存在。可用表: {store.get_tables()}"

        lines = [f"## 表: {table_name}"]
        lines.append("\n### 列信息:")
        for col in schema:
            lines.append(f"  - {col['name']} ({col['type']})")

        # 预览前3行
        preview = store.preview(table_name, limit=3)
        lines.append(f"\n### 前3行数据:\n{preview}")

        return "\n".join(lines)
    except Exception as e:
        return f"ERROR: 获取表信息失败: {e}"


@tool
@log_tool_call(tool_name="execute_sql")
def execute_sql(sql: str) -> str:
    """
    执行 SELECT 查询，返回 CSV 格式结果。

    使用规则:
      - 仅支持 SELECT 语句
      - 查询前先用 get_table_info 确认表结构和列名
      - 如果查询报错，仔细阅读错误信息后修改 SQL 重试
      - 不确定列名时先 SELECT * FROM table LIMIT 1 查看

    Args:
        sql: SQL SELECT 语句

    Returns:
        CSV 格式查询结果，或错误信息
    """
    logger.info("[Tool] execute_sql 被调用，SQL: %s", sql[:200])

    store = get_store()
    result, error = store.execute_sql(sql)

    if error:
        logger.warning("[Tool] execute_sql 失败: %s", error)
        return f"ERROR: {error}"

    # 截断过长结果（head+tail 模式，保留数据分布特征）
    # 借鉴 data_analysis_agent 的表格输出截断策略:
    #   大表只显示头5+尾5行 → 改为头50+尾50行，保留足够的分布信息
    lines = result.split("\n")
    if len(lines) > 100:
        head = "\n".join(lines[:50])
        tail = "\n".join(lines[-50:])
        truncated = (
            f"{head}\n\n"
            f"... (省略中间 {len(lines) - 101} 行) ...\n\n"
            f"{tail}"
        )
        logger.info(
            "[Tool] execute_sql 返回 %d 行（head(50)+tail(50) 截断模式）",
            len(lines) - 1,
        )
        return (
            f"{truncated}\n\n"
            f"(结果共 {len(lines) - 1} 行，已截断：显示前50行+后50行。"
            f"如需更精确的数据，请添加 WHERE 或 LIMIT 条件)"
        )

    logger.info("[Tool] execute_sql 返回 %d 行", max(0, len(lines) - 1))
    return result


@tool
@log_tool_call(tool_name="validate_sql")
def validate_sql(sql: str) -> str:
    """
    校验 SQL 语法（使用 EXPLAIN 检查，不实际执行查询）。

    何时调用:
      - 编写复杂 SQL 后，执行前先校验语法
      - SQL 报错后，修改完先校验再执行

    Args:
        sql: 待校验的 SQL SELECT 语句

    Returns:
        校验结果: "VALID" 或错误信息
    """
    logger.info("[Tool] validate_sql: %s", sql[:100])

    store = get_store()
    try:
        clean = sql.strip()
        # 去除注释
        while clean.startswith("--"):
            clean = clean.split("\n", 1)[-1].strip() if "\n" in clean else ""

        result, error = store.execute_sql(f"EXPLAIN {clean}")
        if error:
            return f"INVALID: {error}"
        return "VALID: SQL 语法正确"
    except Exception as e:
        return f"INVALID: {e}"


# ═══════════════════════════════════════════════════════════
# 图表工具
# ═══════════════════════════════════════════════════════════


@tool
@log_tool_call(tool_name="generate_chart", log_args=True)
def generate_chart(
    chart_type: str,
    title: str,
    x_column: str,
    y_column: str,
    data_json: str,
    group_column: str | None = None,
) -> str:
    """
    根据数据生成 Plotly 图表 JSON 配置。

    调用时机:
      - SQL 查询返回了可用于可视化的结构化数据
      - 用户明确要求画图或展示趋势
      - 数据包含数字列和分类列

    Args:
        chart_type:   图表类型: "line" | "bar" | "pie" | "scatter"
        title:        图表标题
        x_column:     X 轴对应的列名（必须在 data_json 中存在）
        y_column:     Y 轴对应的列名（必须在 data_json 中存在）
        data_json:    CSV 数据序列化为 JSON 字符串
        group_column: 分组列名（多线图/分组柱状图时使用）

    Returns:
        Plotly Figure JSON 字符串，前端用 Plotly.js 渲染
    """
    import plotly.graph_objects as go

    logger.info(
        "[Tool] generate_chart: type=%s title=%s x=%s y=%s group=%s",
        chart_type,
        title,
        x_column,
        y_column,
        group_column,
    )

    # 解析输入数据
    try:
        rows = json.loads(data_json)
    except json.JSONDecodeError:
        return "ERROR: data_json 格式错误，请提供有效的 JSON 数组"

    if not rows:
        return "ERROR: 数据为空，无法生成图表"

    # 按分组列分组
    if group_column and group_column in rows[0]:
        groups = {}
        for row in rows:
            key = row[group_column]
            if key not in groups:
                groups[key] = {"x": [], "y": []}
            groups[key]["x"].append(row[x_column])
            groups[key]["y"].append(row[y_column])
    else:
        groups = {"_all": {"x": [], "y": []}}
        for row in rows:
            groups["_all"]["x"].append(row[x_column])
            groups["_all"]["y"].append(row[y_column])

    # 生成 Plotly Figure
    fig = go.Figure()

    chart_funcs = {
        "line": go.Scatter,
        "bar": go.Bar,
        "scatter": go.Scatter,
    }

    trace_func = chart_funcs.get(chart_type, go.Bar)
    mode = "lines+markers" if chart_type == "line" else None

    for group_name, data in groups.items():
        trace_kwargs = {"x": data["x"], "y": data["y"], "name": str(group_name)}
        if mode:
            trace_kwargs["mode"] = mode
        fig.add_trace(trace_func(**trace_kwargs))

    fig.update_layout(
        title=title,
        xaxis_title=x_column,
        yaxis_title=y_column,
        template="plotly_white",
        hovermode="x unified",
    )

    chart_json = fig.to_json()
    logger.info("[Tool] generate_chart 完成，图表 JSON 大小: %d 字符", len(chart_json))
    return chart_json


# ═══════════════════════════════════════════════════════════
# Python 代码执行工具（v3.2: 借鉴 data_analysis_agent）
# ═══════════════════════════════════════════════════════════


@tool
@log_tool_call(tool_name="execute_python_code", log_args=True)
def execute_python_code(code: str) -> str:
    """
    执行自定义 Python 可视化代码，生成高质量图表。

    借鉴 data_analysis_agent 的 IPython 代码执行模式:
      - 变量在多次调用间保持（DataFrame 不用重复加载）
      - 环境已预配置 matplotlib Agg backend + 中文字体
      - pandas/numpy/matplotlib 已预导入（pd, np, plt 开箱即用）

    何时调用:
      - 需要生成高度定制化的图表（数据标签、参考线、多子图、双Y轴等）
      - generate_chart 无法满足需求时（它只支持基础图表类型）
      - 需要在图上标注文字、添加注释、自定义颜色方案
      - 需要迭代修改图表（"把蓝色改成深蓝，标题字号加大"）

    代码规范:
      1. 图片必须保存到 session_output_dir 目录（变量已预注入）
         示例: plt.savefig(os.path.join(session_output_dir, '图表名.png'), dpi=150)
      2. 保存后必须显式调用 plt.close() 释放内存
      3. 必须 print 保存的绝对路径: print(f"图片已保存: {os.path.abspath(file_path)}")
      4. 使用中文字体（已预配置，直接写中文标题即可）
      5. 超过15行的 DataFrame 会自动截断为 head(5)+tail(5)

    可用库: pandas(pd), numpy(np), matplotlib.pyplot(plt), json, os, re, Path

    Args:
        code: Python 代码字符串。示例:
              ```
              df = pd.DataFrame([...])  # 或使用前序步骤中已存在的 DataFrame 变量
              fig, ax = plt.subplots(figsize=(12, 6))
              ax.bar(df['月份'], df['销售额'], color='#2196F3')
              for i, (m, v) in enumerate(zip(df['月份'], df['销售额'])):
                  ax.text(i, v + 50, f'{v:,.0f}', ha='center')
              ax.set_title('月度销售额', fontsize=16, fontweight='bold')
              file_path = os.path.join(session_output_dir, '月度销售额.png')
              plt.savefig(file_path, dpi=150, bbox_inches='tight')
              print(f"图片已保存: {os.path.abspath(file_path)}")
              plt.close()
              ```

    Returns:
        执行结果: 成功时返回 stdout 输出 + 新生成图片路径
                  失败时返回 ERROR: 错误信息
    """
    import os as _os

    from backend.tools.code_executor import get_executor

    logger.info("[Tool] execute_python_code: 代码 %d 字符", len(code))

    # 获取当前会话的执行器（需要先由 Chart Agent 初始化）
    try:
        executor = get_executor()
    except Exception as e:
        return f"ERROR: 代码执行器未初始化: {e}"

    result = executor.execute(code)

    if not result["success"]:
        error_msg = result["error"] or "未知执行错误"
        output = result.get("output", "")
        if output:
            error_msg = f"{error_msg}\n\n部分输出:\n{output[:500]}"
        logger.warning("[Tool] execute_python_code 失败: %s", error_msg[:150])
        return f"ERROR: {error_msg}"

    # ─── 格式化成功结果 ───
    out_parts = []
    output = result.get("output", "")
    if output:
        out_parts.append(f"📊 执行输出:\n{output[:1500]}")

    figures = result.get("figures", [])
    if figures:
        out_parts.append(f"\n🖼️ 本次生成 {len(figures)} 个图表:")
        for f in figures:
            fname = _os.path.basename(f)
            out_parts.append(f"  - {fname} ({f})")

    variables = result.get("variables", {})
    if variables:
        out_parts.append(f"\n📋 新生成变量 ({len(variables)} 个):")
        for vname, vinfo in variables.items():
            out_parts.append(f"  - {vname}: {vinfo}")

    if not out_parts:
        out_parts.append("✅ 代码执行成功（无输出）")

    summary = "\n".join(out_parts)
    logger.info("[Tool] execute_python_code 成功: %d 图表", len(figures))
    return summary


# ═══════════════════════════════════════════════════════════
# 工具列表导出
# ═══════════════════════════════════════════════════════════

# SQL Agent 工具（3个）
SQL_TOOLS = [get_table_info, execute_sql, validate_sql]

# Chart Agent 工具（仅保留高质量路径: matplotlib 代码执行）
CHART_TOOLS = [execute_python_code]

# 全部工具
ALL_TOOLS = SQL_TOOLS + CHART_TOOLS


def create_tools(store=None):
    """
    依赖注入工厂 — 创建工具列表

    用法:
        store = SQLiteStore(...)
        tools = create_tools(store)
        sql_agent = create_sql_agent(llm, tools.sql_tools)

    Returns:
        包含 sql_tools 和 chart_tools 的命名元组
    """
    from collections import namedtuple

    if store is not None:
        set_store(store)

    Tools = namedtuple("Tools", ["sql_tools", "chart_tools", "all_tools"])
    return Tools(
        sql_tools=list(SQL_TOOLS),
        chart_tools=list(CHART_TOOLS),
        all_tools=list(ALL_TOOLS),
    )
