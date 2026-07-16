"""
Report Agent — 报告合成

负责:
  收集 SQL 结果 + 图表 → 汇总为结构化的 Markdown 分析报告

角色类比: 原项目的 Trader（综合决策型 Agent）
LLM 策略: 使用独立高 token LLM（16384），确保长报告不截断

v3.1 改进:
  - 使用 YAML 输出格式（action: report_complete + final_report: |）
  - 支持从 YAML 中提取报告内容（比 JSON 更自然，无需转义多行字符串）
  - 借鉴 data_analysis_agent 的两阶段 prompt 分离设计
"""

import logging

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from backend.agent.utils.state import DataAnalysisState
from backend.prompts import load_prompt
from backend.utils.yaml_parser import parse_yaml_response

logger = logging.getLogger(__name__)

REPORT_SYSTEM_PROMPT = load_prompt("report_agent")


def create_report_agent(llm):
    """
    创建 Report Agent 节点函数

    参考: tradingagents/agents/trader/trader.py 的 create_trader()

    注意: Report Agent 不需要 bind_tools，纯文本生成。
          使用独立高 token LLM（16384），长报告不截断。
    """

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", REPORT_SYSTEM_PROMPT),
            MessagesPlaceholder(variable_name="messages"),
        ]
    )

    chain = prompt | llm

    def report_agent_node(state: DataAnalysisState) -> dict:
        """LangGraph 节点函数"""
        logger.info("[Report Agent] 开始生成报告草稿")

        # 汇总所有 SQL 结果
        sql_results_list = []
        if state.get("sql_query"):
            sql_results_list.append(f"查询: {state['sql_query'][:200]}")
        if state.get("sql_result"):
            # 截断过长结果（报告阶段保留更多上下文）
            result = state["sql_result"]
            if len(result) > 8000:
                result = result[:4000] + "\n...(已截断中间部分)\n" + result[-4000:]
            sql_results_list.append(f"结果:\n{result}")

        sql_results_text = "\n\n".join(sql_results_list) if sql_results_list else "暂无查询结果"

        # 图表文件路径
        chart_files = state.get("chart_files", [])
        chart_files_text = ""
        if chart_files:
            import os as _os
            chart_refs = []
            for cf in chart_files:
                fname = _os.path.basename(cf)
                # 使用相对路径，前端通过 /output/ 代理访问
                chart_refs.append(f"![{fname}](./{fname})")
            chart_files_text = "\n".join(chart_refs)
            logger.info("[Report Agent] 图表文件: %s", chart_files)

        invoke_args = {
            "messages": state["messages"],
            "user_query": state.get("user_query", ""),
            "sql_results": sql_results_text,
            "chart_images": chart_files_text,
        }

        response = chain.invoke(invoke_args)

        raw_content = response.content if hasattr(response, "content") else str(response)

        # ─── YAML 格式解析 ───
        # 尝试从 YAML 输出中提取 final_report 字段
        # 借鉴 data_analysis_agent 的 YAML 协议:
        #   action: report_complete
        #   final_report: |
        #     报告正文（多行字符串无需转义）
        yaml_data = parse_yaml_response(raw_content)
        final_report = yaml_data.get("final_report", "")
        if final_report and len(final_report) > 50:
            report_content = final_report
            logger.info("[Report Agent] 从 YAML 提取报告，长度: %d 字符", len(report_content))
        else:
            # Fallback: 直接使用原始输出
            report_content = raw_content
            logger.info("[Report Agent] 未检测到 YAML 格式，使用原始输出，长度: %d 字符", len(report_content))

        # 如果有图表，在报告中补充图表引用
        chart_json = state.get("chart_json")
        if chart_json and "![图表]" not in report_content and "![" not in report_content:
            chart_title = state.get("chart_config", {}).get("title", "数据可视化图表")
            report_content += f"\n\n## 数据可视化\n\n![{chart_title}](./chart.html)\n"

        return {
            "draft_report": report_content,
            "final_report": report_content,
            "messages": [response],
            "progress_message": "📝 Report Agent: 报告草稿已生成",
        }

    return report_agent_node
