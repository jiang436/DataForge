"""真实 API 基准测试 — 用 DeepSeek API 跑完整分析流程

用法: python scripts/real_benchmark.py
依赖: .env 中 DEEPSEEK_API_KEY 已配置
"""
import os, sys, time, json

# 确保项目根目录在 path
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)

# 1. 加载 .env 配置（由 backend.core.config 完成）
from backend.core.config import get_settings
settings = get_settings()
print(f"Provider: {settings.llm_provider}")
print(f"API Key:  {settings.deepseek_api_key[:12]}...{settings.deepseek_api_key[-4:]}")

# 2. 准备数据
from backend.dataflows.sqlite_store import SQLiteStore
from backend.tools import set_store

store = SQLiteStore(db_path=":memory:")
set_store(store)

import glob
csv_files = glob.glob(os.path.join(ROOT, "data", "*.csv"))
for f in csv_files:
    name = os.path.splitext(os.path.basename(f))[0]
    store.import_csv(f, table_name=name)
    print(f"  导入: {os.path.basename(f)} → '{name}'")

tables = store.get_tables()
schemas_text = store.get_schemas_text()
print(f"  表: {tables}")

# 3. 初始化
from backend.graph.orchestrator import DataAgentGraph
from backend.llm_clients.factory import get_token_tracker

print("\n初始化 Orchestrator...")
t0 = time.time()
orch = DataAgentGraph(provider=settings.llm_provider, store=store, max_debate_rounds=2)
print(f"  耗时: {time.time() - t0:.1f}s")

# 重置 TokenTracker
tracker = get_token_tracker()
tracker.reset()

# 4. 运行分析
QUERY = "哪个品牌性价比最高？综合价格、销量、好评率、折扣率来分析"
print(f"\n分析: {QUERY}")
print("=" * 60)

t_start = time.time()

final_state, performance = orch.propagate(
    user_query=QUERY,
    available_tables=tables,
    table_schemas_text=schemas_text,
    progress_callback=lambda msg: print(
        f"  [{msg.get('agent', '?')}] {msg.get('progress', str(msg))[:120]}"
    ),
)

total_time = time.time() - t_start

# 5. 输出结果
snap = tracker.snapshot()
perf = performance or {}

print("\n" + "=" * 60)
print(f"=== 实测结果 ===\n")
print(f"  总耗时:          {total_time:.1f}s")
print(f"  Token 输入:      {snap['input_tokens']:,}")
print(f"  Token 输出:      {snap['output_tokens']:,}")
print(f"  Token 总计:      {snap['total_tokens']:,}")
print(f"  LLM 调用次数:    {snap['call_count']}")
print(f"  节点数:          {perf.get('node_count', 0)}")
print(f"  Validator:       {final_state.get('validation_result', '?')}")
print(f"  修订次数:        {final_state.get('revision_count', 0)}")

debate = final_state.get('debate_scores', {})
if debate:
    print(f"  辩论:           正方={debate.get('optimistic_score',0)} 反方={debate.get('pessimistic_score',0)} 胜方={debate.get('winner','?')}")
print(f"  报告长度:        {len(final_state.get('final_report', ''))} 字符")

print(f"\n--- 节点耗时 ---")
node_timings = perf.get("node_timings", {})
for name, t in sorted(node_timings.items(), key=lambda x: x[1], reverse=True):
    pct = t / total_time * 100 if total_time > 0 else 0
    bar = "█" * max(1, int(pct))
    print(f"  {name:25s} {t:7.2f}s ({pct:5.1f}%) {bar}")

# 保存
result = {
    "query": QUERY,
    "total_time_s": round(total_time, 1),
    "token_input": snap["input_tokens"],
    "token_output": snap["output_tokens"],
    "token_total": snap["total_tokens"],
    "call_count": snap["call_count"],
    "node_count": perf.get("node_count", 0),
    "node_timings": node_timings,
    "validation_result": final_state.get("validation_result"),
    "debate_scores": {k: v for k, v in debate.items() if k in ("optimistic_score", "pessimistic_score", "winner")},
}

out_path = os.path.join(ROOT, "docs", "benchmark_result.json")
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)
print(f"\n结果: {out_path}")

store.close()
print("=== 完成 ===")
