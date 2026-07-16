<template>
  <div class="report-panel" v-if="hasContent">
    <!-- Tabs -->
    <div class="rp-tabs">
      <button
        v-for="tab in visibleTabs"
        :key="tab.key"
        class="rp-tab"
        :class="{ active: activeTab === tab.key }"
        @click="activeTab = tab.key"
      >
        {{ tab.label }}
        <span class="tab-badge" v-if="tab.count">{{ tab.count }}</span>
      </button>

      <div class="rp-actions">
        <select v-model="exportFormat" class="export-select">
          <option value="md">.md</option>
          <option value="docx">.docx</option>
          <option value="html">.html</option>
          <option value="tree">.zip (完整)</option>
        </select>
        <button class="export-btn" @click="handleExport" :disabled="exporting">
          {{ exporting ? '导出中...' : '导出' }}
        </button>
      </div>
    </div>

    <!-- Panel content -->
    <div class="rp-content">
      <!-- Report tab -->
      <div v-if="activeTab === 'report'" class="report-view">
        <div class="report-body" v-html="renderedReport"></div>
      </div>

      <!-- Charts tab -->
      <div v-if="activeTab === 'charts'" class="charts-view">
        <div v-if="chartMessages.length === 0" class="empty-tab">
          暂无图表 — 图表将在分析过程中实时生成
        </div>
        <div v-for="(chart, i) in chartMessages" :key="i" class="chart-gallery-item">
          <ChartCard :chart-json="chart.chartJson" />
        </div>
      </div>

      <!-- SQL tab -->
      <div v-if="activeTab === 'sql'" class="sql-view">
        <div v-if="sqlMessages.length === 0" class="empty-tab">
          暂无 SQL 查询
        </div>
        <div v-for="(sql, i) in sqlMessages" :key="i" class="sql-block">
          <div class="sql-header">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>
            <span>SQL 查询 #{{ i + 1 }}</span>
          </div>
          <pre><code>{{ sql.content }}</code></pre>
        </div>
      </div>

      <!-- Debate tab -->
      <div v-if="activeTab === 'debate'" class="debate-view">
        <div v-if="debateMessages.length === 0" class="empty-tab">
          暂无辩论记录（完整模式才启用辩论）
        </div>
        <div v-for="(d, i) in debateMessages" :key="i" class="debate-block" :class="d.agent === 'Optimistic' ? 'opt' : 'pess'">
          <div class="debate-label">{{ d.agent === 'Optimistic' ? '乐观视角' : '谨慎视角' }}</div>
          <div class="debate-text">{{ d.content?.slice(0, 600) }}{{ d.content?.length > 600 ? '...' : '' }}</div>
        </div>
        <!-- Debate scores -->
        <div v-if="debateScores.length" class="scores-section">
          <div v-for="(s, i) in debateScores" :key="i" class="score-row">
            <div class="score-item opt">
              <span class="score-num">{{ s.optScore || '--' }}</span>
              <span class="score-lbl">乐观方</span>
            </div>
            <div class="score-vs">{{ s.winnerLabel || 'vs' }}</div>
            <div class="score-item pess">
              <span class="score-num">{{ s.pessScore || '--' }}</span>
              <span class="score-lbl">谨慎方</span>
            </div>
          </div>
        </div>
      </div>

      <!-- Eval tab -->
      <div v-if="activeTab === 'eval'" class="eval-view">
        <div v-if="evalMessages.length === 0" class="empty-tab">
          暂无评估结果
        </div>
        <div v-for="(e, i) in evalMessages" :key="i" class="eval-card" :class="{ pass: e._eval?.passed, fail: !e._eval?.passed }">
          <div class="eval-score">{{ ((e._eval?.overall_score || 0) * 100).toFixed(0) }}</div>
          <div class="eval-status">{{ e._eval?.passed ? '通过' : '需改进' }}</div>
          <div class="eval-warnings" v-if="e._eval?.warnings?.length">
            <div v-for="(w, j) in e._eval.warnings.slice(0, 5)" :key="j" class="eval-warning">{{ w }}</div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from "vue";
import { useChatStore } from "@/stores/chat";
import ChartCard from "@/components/ChartCard.vue";
import { marked } from "marked";
import DOMPurify from "dompurify";

const chat = useChatStore();
const activeTab = ref("report");
const exportFormat = ref("md");
const exporting = ref(false);

marked.setOptions({ breaks: true, gfm: true });

const chartMessages = computed(() =>
  chat.messages.filter((m) => m.type === "chart" && m.chartJson)
);
const sqlMessages = computed(() =>
  chat.messages.filter((m) => m.type === "sql")
);
const debateMessages = computed(() =>
  chat.messages.filter((m) => m.type === "debate")
);
const debateScores = computed(() =>
  chat.messages.filter((m) => m.type === "debate_score")
);
const evalMessages = computed(() =>
  chat.messages.filter((m) => m.type === "eval" && m._eval)
);

const reportContent = computed(() => {
  for (let i = chat.messages.length - 1; i >= 0; i--) {
    if (chat.messages[i].type === "report") return chat.messages[i].content;
  }
  return "";
});

const renderedReport = computed(() => {
  const raw = marked.parse(reportContent.value || "*等待分析完成...*") as string;
  return DOMPurify.sanitize(raw);
});

const hasContent = computed(
  () => chat.messages.length > 0
);

const visibleTabs = computed(() => {
  const tabs: { key: string; label: string; count?: number }[] = [
    { key: "report", label: "报告" },
  ];
  if (chartMessages.value.length) tabs.push({ key: "charts", label: "图表", count: chartMessages.value.length });
  if (sqlMessages.value.length) tabs.push({ key: "sql", label: "SQL", count: sqlMessages.value.length });
  if (debateMessages.value.length) tabs.push({ key: "debate", label: "辩论" });
  if (evalMessages.value.length) tabs.push({ key: "eval", label: "评估" });
  return tabs;
});

async function handleExport() {
  exporting.value = true;
  try {
    const state: Record<string, unknown> = {
      format: exportFormat.value,
      final_report: reportContent.value,
      query: chat.messages.find((m) => m.role === "user")?.content || "",
      chart_json: chartMessages.value[chartMessages.value.length - 1]?.chartJson,
      sql_query: sqlMessages.value.map((m) => m.content).join("\n\n"),
      plan: chat.agentResults?.planner?.plan || [],
      debate_scores: debateScores.value.length ? {
        optimistic_score: debateScores.value[0].optScore,
        pessimistic_score: debateScores.value[0].pessScore,
        winner_label: debateScores.value[0].winnerLabel,
      } : null,
    };

    const resp = await fetch("/api/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(state),
    });

    if (resp.ok) {
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `report_${Date.now()}.${exportFormat.value === "tree" ? "zip" : exportFormat.value}`;
      a.click();
      URL.revokeObjectURL(url);
    }
  } catch (e) {
    console.error("Export failed:", e);
  } finally {
    exporting.value = false;
  }
}
</script>

<style scoped>
.report-panel {
  background: var(--stone-surface);
  border: 1px solid var(--stone-border);
  border-radius: var(--radius-lg);
  overflow: hidden;
  display: flex;
  flex-direction: column;
  height: 100%;
}

.rp-tabs {
  display: flex;
  align-items: center;
  gap: 0;
  border-bottom: 1px solid var(--stone-border);
  background: var(--stone-hover);
  padding: 0 8px;
}

.rp-tab {
  padding: 10px 16px;
  font-size: 13px;
  font-weight: 500;
  color: var(--ink-secondary);
  background: none;
  border: none;
  border-bottom: 2px solid transparent;
  cursor: pointer;
  transition: all var(--duration-fast);
  display: flex;
  align-items: center;
  gap: 6px;
  font-family: var(--font-sans);
}

.rp-tab:hover { color: var(--ink-primary); }

.rp-tab.active {
  color: var(--accent);
  border-bottom-color: var(--accent);
}

.tab-badge {
  font-size: 10px;
  padding: 1px 6px;
  background: var(--stone-border);
  border-radius: 99px;
  color: var(--ink-secondary);
  font-family: var(--font-mono);
}

.rp-actions {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 6px;
}

.export-select {
  font-size: 11px;
  padding: 4px 8px;
  border: 1px solid var(--stone-border);
  border-radius: var(--radius-sm);
  background: var(--stone-surface);
  color: var(--ink-secondary);
  font-family: var(--font-mono);
  cursor: pointer;
}

.export-btn {
  font-size: 12px;
  padding: 5px 14px;
  background: var(--accent);
  color: white;
  border: none;
  border-radius: var(--radius-sm);
  cursor: pointer;
  font-weight: 520;
  transition: background var(--duration-fast);
}

.export-btn:hover { background: var(--accent-strong); }
.export-btn:disabled { opacity: 0.5; cursor: not-allowed; }

.rp-content {
  flex: 1;
  overflow-y: auto;
  padding: 24px 28px;
}

.report-body {
  font-size: 14px;
  line-height: 1.8;
  color: var(--ink-primary);
}

/* Report typography — taste-skill style */
.report-body :deep(h1) { font-size: 22px; font-weight: 700; margin: 28px 0 10px; letter-spacing: -0.02em; }
.report-body :deep(h2) { font-size: 18px; font-weight: 650; margin: 24px 0 8px; letter-spacing: -0.01em; }
.report-body :deep(h3) { font-size: 15px; font-weight: 600; margin: 20px 0 6px; }
.report-body :deep(p) { margin: 8px 0; }
.report-body :deep(table) { width: 100%; border-collapse: collapse; margin: 14px 0; font-size: 13px; }
.report-body :deep(th) {
  background: var(--stone-hover); padding: 10px 14px; text-align: left; font-weight: 600;
  border-bottom: 2px solid var(--stone-border); font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em;
}
.report-body :deep(td) { padding: 8px 14px; border-bottom: 1px solid var(--stone-border); font-family: var(--font-mono); font-size: 12.5px; }
.report-body :deep(code) { font-family: var(--font-mono); font-size: 12.5px; background: var(--stone-hover); padding: 2px 6px; border-radius: 4px; }
.report-body :deep(pre) { background: var(--stone-bg); border: 1px solid var(--stone-border); border-radius: var(--radius-md); padding: 16px; overflow-x: auto; }
.report-body :deep(blockquote) { border-left: 3px solid var(--accent); padding: 8px 16px; margin: 12px 0; color: var(--ink-secondary); background: var(--accent-bg); }

.empty-tab {
  padding: 48px 20px;
  text-align: center;
  color: var(--ink-tertiary);
  font-size: 13px;
}

/* Charts gallery */
.charts-view { display: flex; flex-direction: column; gap: 20px; }

/* SQL */
.sql-block {
  background: var(--stone-bg); border: 1px solid var(--stone-border); border-radius: var(--radius-md);
  overflow: hidden; margin-bottom: 14px;
}
.sql-header {
  display: flex; align-items: center; gap: 7px; padding: 8px 14px;
  background: var(--stone-hover); border-bottom: 1px solid var(--stone-border);
  font-size: 11px; font-weight: 550; color: var(--ink-secondary); text-transform: uppercase; letter-spacing: 0.04em;
}
.sql-block pre { padding: 14px 16px; margin: 0; overflow-x: auto; font-family: var(--font-mono); font-size: 12.5px; }

/* Debate */
.debate-block {
  padding: 16px 18px; border-radius: var(--radius-md); margin-bottom: 12px; font-size: 13px;
  background: var(--stone-surface); border: 1px solid var(--stone-border);
}
.debate-block.opt { border-left: 3px solid var(--accent); background: var(--accent-bg); }
.debate-block.pess { border-left: 3px solid var(--amber); background: var(--amber-bg); }
.debate-label { font-size: 11.5px; font-weight: 600; letter-spacing: 0.03em; margin-bottom: 8px; }
.opt .debate-label { color: var(--accent); }
.pess .debate-label { color: var(--amber); }
.debate-text { color: var(--ink-secondary); line-height: 1.65; }

/* Scores */
.scores-section { margin-top: 12px; }
.score-row { display: flex; align-items: center; gap: 0; padding: 12px 20px; background: var(--stone-hover); border-radius: var(--radius-md); }
.score-item { flex: 1; display: flex; flex-direction: column; align-items: center; }
.score-num { font-size: 24px; font-weight: 700; font-family: var(--font-mono); }
.opt .score-num { color: var(--accent); }
.pess .score-num { color: var(--amber); }
.score-lbl { font-size: 10px; color: var(--ink-tertiary); text-transform: uppercase; }
.score-vs { padding: 0 20px; font-size: 11px; font-weight: 600; color: var(--ink-primary); }

/* Eval */
.eval-card { padding: 20px; border-radius: var(--radius-md); text-align: center; margin-bottom: 12px; }
.eval-card.pass { background: var(--accent-bg); border: 1px solid var(--accent-border); }
.eval-card.fail { background: var(--amber-bg); border: 1px solid var(--amber-border); }
.eval-score { font-size: 36px; font-weight: 700; font-family: var(--font-mono); letter-spacing: -0.02em; }
.pass .eval-score { color: var(--accent); }
.fail .eval-score { color: var(--amber); }
.eval-status { font-size: 13px; margin-top: 4px; color: var(--ink-secondary); }
.eval-warnings { margin-top: 12px; text-align: left; }
.eval-warning { font-size: 12px; padding: 4px 0; color: var(--amber); }
</style>
