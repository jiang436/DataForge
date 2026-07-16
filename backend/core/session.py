"""
会话文件系统隔离模块

借鉴: data_analysis_agent 的 UUID 会话隔离模式 —
      每次分析创建独立的输出目录，所有图表/报告/SQL结果落在会话目录。

收益:
  - 调试方便：每个会话的产物集中存放
  - 可复现：完整的分析记录可回溯
  - 便于下载：一键打包整个会话产物

用法:
    from backend.core.session import SessionContext
    ctx = SessionContext()
    ctx.save_report(report_md)
    ctx.save_chart(chart_json, "sales_trend")
    ctx.save_sql_result(csv_data, "query_1")
    # 产物全部在: output/session_abc123/
"""

import csv
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ─── 会话产物输出根目录 ───
DEFAULT_OUTPUT_ROOT = Path("output")


class SessionContext:
    """
    会话上下文 — 管理单次分析的文件系统产物。

    每次 DataAgentGraph.propagate() 调用创建一个 SessionContext，
    所有中间产物（报告、图表、SQL 结果）保存到独立目录。

    面试话术: "我实现了 UUID 会话隔离，每次分析创建独立目录存放所有产物，
            调试/复现/下载都很方便，这是从 data_analysis_agent 借鉴的设计。"
    """

    def __init__(
        self,
        session_id: str | None = None,
        output_root: Path | str = DEFAULT_OUTPUT_ROOT,
        user_query: str = "",
    ):
        """
        Args:
            session_id:   会话 ID，不传则自动生成 UUID（取前 12 位）
            output_root:  输出根目录
            user_query:   用户问题（写入 README.md 供回溯）
        """
        self.session_id = session_id or uuid.uuid4().hex[:12]
        self.output_root = Path(output_root)
        self.session_dir = self.output_root / f"session_{self.session_id}"
        self.created_at = datetime.now(timezone.utc)

        # 创建会话目录
        self.session_dir.mkdir(parents=True, exist_ok=True)
        logger.info("[Session] 会话目录已创建: %s", self.session_dir)

        # 记录元信息
        self._write_metadata(user_query)

    def _write_metadata(self, user_query: str):
        """写入会话元信息"""
        meta = {
            "session_id": self.session_id,
            "created_at": self.created_at.isoformat(),
            "user_query": user_query[:500] if user_query else "",
        }
        meta_path = self.session_dir / "metadata.json"
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    # ─── 保存方法 ───

    def save_report(self, report: str, filename: str = "report.md") -> Path:
        """
        保存分析报告

        自动将报告中的绝对路径替换为相对路径，确保报告可移植。
        借鉴 data_analysis_agent 的相对路径约定。

        Args:
            report:    Markdown 格式报告
            filename:  文件名

        Returns:
            保存的文件路径
        """
        # ─── 相对路径转换 ───
        # 将绝对路径引用（如 D:/output/session_xxx/chart.png）转为相对路径（./chart.png）
        import re
        session_dir_str = str(self.session_dir).replace("\\", "/")
        report = re.sub(
            rf'!\[([^\]]*)\]\({re.escape(session_dir_str)}/([^)]+)\)',
            r'![\1](./\2)',
            report,
        )
        # 也处理没有 session_dir 前缀的图表引用
        report = re.sub(
            rf'!\[([^\]]*)\]\({re.escape(str(self.session_dir))}\\?([^)]+)\)',
            r'![\1](./\2)',
            report,
        )

        path = self.session_dir / filename
        path.write_text(report, encoding="utf-8")
        logger.info("[Session] 报告已保存: %s (%d 字符, 已转相对路径)", path, len(report))
        return path

    def save_chart(self, chart_json: dict | str, name: str = "chart") -> Path:
        """
        保存图表 JSON/HTML

        Args:
            chart_json: Plotly Figure JSON 或 HTML 字符串
            name:       图表名称（不含扩展名）

        Returns:
            保存的文件路径
        """
        # 保存 JSON（Plotly 格式）
        json_path = self.session_dir / f"{name}.json"
        if isinstance(chart_json, dict):
            json_path.write_text(
                json.dumps(chart_json, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        else:
            json_path.write_text(str(chart_json), encoding="utf-8")

        # 同时保存为独立 HTML（可直接浏览器打开）
        html_path = self.session_dir / f"{name}.html"
        html_content = self._chart_json_to_html(chart_json)
        if html_content:
            html_path.write_text(html_content, encoding="utf-8")
            logger.info("[Session] 图表已保存: %s + %s", json_path, html_path)
        else:
            logger.info("[Session] 图表 JSON 已保存: %s", json_path)

        return json_path

    def save_sql_result(self, csv_data: str, name: str = "query_result") -> Path:
        """
        保存 SQL 查询结果

        Args:
            csv_data: CSV 格式查询结果
            name:     文件名（不含扩展名）

        Returns:
            保存的文件路径
        """
        path = self.session_dir / f"{name}.csv"
        path.write_text(csv_data, encoding="utf-8")
        logger.info("[Session] SQL 结果已保存: %s (%d 行)", path, len(csv_data.split("\n")))
        return path

    def save_debate_transcript(self, optimistic: str, pessimistic: str) -> Path:
        """
        保存辩论记录

        Args:
            optimistic:  正方（乐观）观点
            pessimistic: 反方（悲观）观点

        Returns:
            保存的文件路径
        """
        content = f"""# 辩论记录 (Session {self.session_id})

## 🔵 正方（乐观方）
{optimistic}

---

## 🔴 反方（谨慎方）
{pessimistic}
"""
        path = self.session_dir / "debate.md"
        path.write_text(content, encoding="utf-8")
        logger.info("[Session] 辩论记录已保存: %s", path)
        return path

    def save_evaluation(self, evaluation: dict) -> Path:
        """保存评估结果"""
        path = self.session_dir / "evaluation.json"
        path.write_text(
            json.dumps(evaluation, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        logger.info("[Session] 评估结果已保存: %s", path)
        return path

    def save_plan(self, plan: list[dict]) -> Path:
        """保存执行计划"""
        path = self.session_dir / "plan.json"
        path.write_text(
            json.dumps(plan, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("[Session] 执行计划已保存: %s", path)
        return path

    def save_performance(self, performance: dict) -> Path:
        """保存性能指标"""
        path = self.session_dir / "performance.json"
        path.write_text(
            json.dumps(performance, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("[Session] 性能数据已保存: %s", path)
        return path

    # ─── 读取方法 ───

    def list_files(self) -> list[Path]:
        """列出会话目录中的所有产物文件"""
        return sorted(
            p for p in self.session_dir.iterdir()
            if p.is_file() and not p.name.startswith(".")
        )

    def get_manifest(self) -> dict[str, Any]:
        """获取会话产物清单"""
        files = self.list_files()
        return {
            "session_id": self.session_id,
            "created_at": self.created_at.isoformat(),
            "directory": str(self.session_dir),
            "files": [
                {
                    "name": f.name,
                    "size": f.stat().st_size,
                    "type": f.suffix,
                }
                for f in files
            ],
        }

    # ─── 工具方法 ───

    @staticmethod
    def _chart_json_to_html(chart_json: dict | str) -> str | None:
        """将 Plotly Figure JSON 转换为独立 HTML"""
        try:
            if isinstance(chart_json, str):
                fig_data = json.loads(chart_json)
            else:
                fig_data = chart_json

            if "data" not in fig_data:
                return None

            return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>DataForge AI — Chart</title>
    <script src="https://cdn.plot.ly/plotly-2.32.0.min.js"></script>
    <style>
        body {{ margin: 0; display: flex; justify-content: center; align-items: center;
               min-height: 100vh; background: #f5f5f5; }}
        #chart {{ width: 95vw; height: 90vh; }}
    </style>
</head>
<body>
    <div id="chart"></div>
    <script>
        Plotly.newPlot("chart", {json.dumps(fig_data['data'], ensure_ascii=False)},
                       {json.dumps(fig_data.get('layout', {}), ensure_ascii=False)},
                       {{ responsive: true }});
    </script>
</body>
</html>"""
        except Exception as e:
            logger.warning("[Session] 图表 HTML 生成失败: %s", e)
            return None


# ─── 便捷函数 ───


def create_session(
    user_query: str = "",
    output_root: Path | str = DEFAULT_OUTPUT_ROOT,
) -> SessionContext:
    """
    创建新的分析会话上下文

    Args:
        user_query:  用户问题
        output_root: 输出根目录

    Returns:
        SessionContext 实例
    """
    return SessionContext(user_query=user_query, output_root=output_root)


def list_all_sessions(output_root: Path | str = DEFAULT_OUTPUT_ROOT) -> list[dict]:
    """
    列出所有历史会话

    Returns:
        [{session_id, created_at, file_count, directory}, ...]
    """
    root = Path(output_root)
    if not root.exists():
        return []

    sessions = []
    for d in sorted(root.iterdir(), reverse=True):
        if d.is_dir() and d.name.startswith("session_"):
            meta_path = d / "metadata.json"
            meta = {}
            if meta_path.exists():
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                except Exception:
                    pass
            files = [p for p in d.iterdir() if p.is_file() and not p.name.startswith(".")]
            sessions.append({
                "session_id": meta.get("session_id", d.name.replace("session_", "")),
                "created_at": meta.get("created_at", ""),
                "user_query": meta.get("user_query", "")[:100],
                "file_count": len(files),
                "directory": str(d),
            })
    return sessions
