"""生成 README 流程图 PNG — 高分辨率 + 自动裁边"""
import subprocess
from pathlib import Path
from PIL import Image, ImageChops

ROOT = Path(__file__).parent.parent
IMG = ROOT / "docs" / "images"
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

# 紧凑模板：body 不居中，让 Mermaid 填满视口
TEMPLATE = """<!DOCTYPE html>
<html><head><meta charset="utf-8">
<script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
<style>*{{margin:0;padding:0}} body{{background:#fff}} .mermaid{{display:inline-block;padding:24px 28px;font-family:system-ui,sans-serif;font-size:15px}}</style>
</head><body><div class="mermaid">
{code}
</div>
<script>mermaid.initialize({{startOnLoad:true,theme:'default'}});</script>
</body></html>"""

# 每个图的视口尺寸 (宽,高)
CONFIGS = {
    "business-flow":       ("1800", "1600"),  # 宽屏让竖向流程图更多空间
    "architecture":        ("1800", "1200"),  # 横向架构图
    "conditional-routing": ("1600", "1400"),  # 状态图
}

DIAGRAMS = {
    "business-flow": """flowchart TD
    U["👤 用户上传 CSV + 提问"] --> P["① Planner<br/>任务拆解为执行步骤"]
    P --> S["② SQL Agent<br/>查表结构 → 生成SQL → 执行"]
    S --> ST["🔧 execute_sql<br/>SQLite 查询"]
    ST -->|"错误 ≤2次"| S
    ST -->|成功| C["③ Chart Agent<br/>数据 → Plotly 图表 JSON"]
    C --> CT["🔧 generate_chart<br/>柱状图/折线图/散点图"]
    CT --> R["④ Report Agent<br/>汇总 SQL 结果 + 图表"]
    R --> D{"⑤ Optimistic ⇄ ⑥ Pessimistic<br/>2 轮对抗辩论"}
    D --> DS["🏆 DebateScorer<br/>三维量化评分"]
    DS --> V{"⑦ Validator<br/>裁判验证"}
    V -->|"驳回 ≤3次"| R
    V -->|通过| E["📊 输出报告 + 图表"]
    V -->|"驳回 ≥3次"| F["⚠️ 强制结束"]""",
    "architecture": """graph TD
    subgraph 表现层
        A1["Vue 3 + Element Plus<br/>对话式 UI"]
        A2["Plotly.js<br/>交互图表渲染"]
        A3["SSE 流式接收<br/>Token 级实时展示"]
    end
    subgraph 网关层
        B1["FastAPI Middleware<br/>API Key 鉴权"]
        B2["ErrorHandler<br/>全局异常拦截"]
        B3["RateLimiter<br/>滑动窗口限流"]
    end
    subgraph 业务层
        C1["LangGraph 编排引擎<br/>StateGraph + 条件路由"]
        C2["7 个 AI Agent<br/>Planner / SQL / Chart / Report<br/>Optimistic / Pessimistic / Validator"]
        C3["DebateScorer<br/>辩论评分器"]
    end
    subgraph 工具层
        D1["execute_sql<br/>SQL 白名单安全校验"]
        D2["generate_chart<br/>Plotly JSON 生成"]
        D3["ChromaDB<br/>向量记忆检索"]
    end
    subgraph 持久层
        E1[("SQLite<br/>CSV 数据存储")]
        E2[("ChromaDB<br/>上下文记忆")]
        E3[("文件系统<br/>报告 MD/DOCX/HTML")]
    end
    A1 --> B1 --> C1
    A2 --> A1
    A3 --> A1
    C1 --> C2
    C2 --> D1
    C2 --> D2
    C2 --> D3
    C3 --> C2
    D1 --> E1
    D2 --> E3
    D3 --> E2""",
    "conditional-routing": """stateDiagram-v2
    [*] --> SQL_Agent
    state SQL_Agent {
        [*] --> 生成SQL
        生成SQL --> 执行SQL: tool_calls
        执行SQL --> 处理结果: 成功
        执行SQL --> 错误修正: sql_error &amp; retry&lt;2
        错误修正 --> 生成SQL
        处理结果 --> [*]
    }
    SQL_Agent --> Chart_Agent: 正常
    SQL_Agent --> Chart_Agent: 无数据/跳过
    state Debate {
        [*] --> Optimistic发言
        Optimistic发言 --> Pessimistic发言
        Pessimistic发言 --> Optimistic发言: round &lt; max×2
        Pessimistic发言 --> [*]: 辩论结束
    }
    Chart_Agent --> Report_Agent
    Report_Agent --> Debate
    Debate --> Validator
    state Validator {
        [*] --> 一致性检查
        一致性检查 --> 通过: approved
        一致性检查 --> 驳回修正: rejected &amp; revision&lt;3
        一致性检查 --> 强制结束: revision≥3
    }
    通过 --> [*]
    驳回修正 --> Report_Agent
    强制结束 --> [*]""",
}



def crop_whitespace(img: Image.Image, border: int = 20) -> Image.Image:
    """裁掉纯白/近白边缘"""
    bg = Image.new(img.mode, img.size, (255, 255, 255))
    diff = ImageChops.difference(img, bg)
    bbox = diff.getbbox()
    if bbox:
        return img.crop((
            max(0, bbox[0] - border),
            max(0, bbox[1] - border),
            min(img.width, bbox[2] + border),
            min(img.height, bbox[3] + border),
        ))
    return img


for name, code in DIAGRAMS.items():
    html_path = IMG / f"{name}.html"
    png_path = IMG / f"{name}.png"
    html_path.write_text(TEMPLATE.replace("{code}", code), encoding="utf-8")
    width, height = CONFIGS[name]
    print(f"Screenshot {name} ({width}x{height} @2x)...", end=" ", flush=True)
    subprocess.run(
        [CHROME, "--headless=new", f"--screenshot={png_path}",
         f"--window-size={width},{height}", "--force-device-scale-factor=2",
         f"file:///{html_path.as_posix()}"],
        capture_output=True, timeout=30,
    )
    html_path.unlink()

    # 裁白边
    img = Image.open(png_path)
    orig_w, orig_h = img.size
    img = crop_whitespace(img)
    new_w, new_h = img.size
    img.save(png_path, "PNG", optimize=True)
    kb = png_path.stat().st_size / 1024
    print(f"OK {orig_w}x{orig_h} → {new_w}x{new_h} ({kb:.0f} KB)")

print("\nDone!")
