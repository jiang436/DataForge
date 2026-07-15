<template>
  <div class="chat-shell">
    <!-- Header: clean, minimal -->
    <header class="chat-header">
      <div class="header-left">
        <span class="stage-badge" v-if="chat.isProcessing">{{ chat.currentStage }}</span>
        <span class="stage-idle" v-else>就绪</span>
      </div>
      <div class="header-right">
        <span class="eval-badge" v-if="lastEval" :class="{ pass: lastEval.passed, fail: !lastEval.passed }">
          评分: {{ (lastEval.overall_score * 100).toFixed(0) }}
        </span>
        <button class="clear-btn" @click="chat.clearMessages()" v-if="chat.messages.length">清除</button>
      </div>
    </header>

    <!-- Body -->
    <div ref="scrollEl" class="chat-body" v-if="chat.messages.length">
      <template v-for="msg in chat.messages" :key="msg.id">
        <!-- User message -->
        <div v-if="msg.role === 'user'" class="msg-row user">
          <div class="user-bubble">{{ msg.content }}</div>
        </div>

        <!-- Agent step: timeline style -->
        <div v-else-if="msg.type === 'step'" class="step-row">
          <div class="step-indicator">
            <span class="step-dot" :class="stepColorClass(msg.agent)"></span>
            <span class="step-line" v-if="!isLastStep(msg.id)"></span>
          </div>
          <div class="step-content">
            <span class="step-agent">{{ msg.agentLabel || msg.agent }}</span>
            <span class="step-msg">{{ msg.content }}</span>
            <!-- Streaming token display -->
            <span
              v-if="chat.currentStreamingAgent === msg.agent && chat.streamingTokens[msg.agent]"
              class="token-stream"
            >{{ chat.streamingTokens[msg.agent] }}<span class="cursor-blink">|</span></span>
          </div>
        </div>

        <!-- SQL code block -->
        <div v-else-if="msg.type === 'sql'" class="sql-block">
          <div class="sql-header">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>
            <span>SQL 查询</span>
          </div>
          <pre><code>{{ msg.content }}</code></pre>
        </div>

        <!-- Debate cards: side-by-side with left border accents -->
        <div v-else-if="msg.type === 'debate'" class="debate-card" :class="msg.agent === 'Optimistic' ? 'opt' : 'pess'">
          <div class="debate-header">
            <span class="debate-label">{{ msg.agent === 'Optimistic' ? '乐观视角' : '谨慎视角' }}</span>
          </div>
          <div class="debate-body">{{ msg.content?.slice(0, 400) }}{{ msg.content?.length > 400 ? '...' : '' }}</div>
        </div>

        <!-- Debate scores -->
        <div v-else-if="msg.type === 'debate_score'" class="score-row">
          <div class="score-card opt-score">
            <span class="score-value">{{ msg.optScore || '--' }}</span>
            <span class="score-label">Optimistic</span>
          </div>
          <div class="score-divider">
            <span class="score-winner">{{ msg.winnerLabel || 'vs' }}</span>
          </div>
          <div class="score-card pess-score">
            <span class="score-value">{{ msg.pessScore || '--' }}</span>
            <span class="score-label">Pessimistic</span>
          </div>
        </div>

        <!-- Chart -->
        <div v-else-if="msg.type === 'chart'" class="chart-wrapper">
          <ChartCard :chart-json="msg.chartJson" />
        </div>

        <!-- Report: clean prose card -->
        <div v-else-if="msg.type === 'report' || msg.role === 'assistant'" class="report-card">
          <div class="report-body" v-html="renderMd(msg.content)" />
        </div>
      </template>
    </div>

    <!-- Empty state -->
    <div class="chat-body empty-state" v-else>
      <div class="empty-inner">
        <div class="empty-icon">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.2">
            <ellipse cx="12" cy="5" rx="9" ry="3"/>
            <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/>
            <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/>
          </svg>
        </div>
        <h2 class="empty-heading">数据分析</h2>
        <p class="empty-desc">7 个 AI Agent 协作：数据查询 → 图表生成 → 辩论 → 验证，自动产出带图表的分析报告。</p>
        <div class="quick-row">
          <button v-for="q in prompts" :key="q" @click="quick(q)" :disabled="chat.isProcessing" class="quick-chip">
            {{ q }}
          </button>
        </div>
      </div>
    </div>

    <!-- Input footer -->
    <div class="chat-footer">
      <div class="input-wrap">
        <textarea
          v-model="input"
          placeholder="输入数据分析问题..."
          :disabled="chat.isProcessing"
          rows="1"
          @keydown.enter.exact.prevent="submit"
          @input="autoResize"
          ref="inputEl"
        ></textarea>
        <button class="send-btn" @click="submit" :disabled="chat.isProcessing || !input.trim()">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
            <line x1="12" y1="19" x2="12" y2="5"/>
            <polyline points="5 12 12 5 19 12"/>
          </svg>
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, nextTick, computed } from "vue";
import { useChatStore } from "@/stores/chat";
import { useSSE } from "@/composables/useSSE";
import ChartCard from "@/components/ChartCard.vue";
import { marked } from "marked";
import DOMPurify from "dompurify";

const chat = useChatStore();
const { send } = useSSE();
const input = ref("");
const scrollEl = ref<HTMLElement>();
const inputEl = ref<HTMLTextAreaElement>();

const prompts = [
  "哪个品牌销量最高？",
  "高折扣率是否意味着高销量？",
  "综合考虑价格、好评率和保修期，哪个品牌性价比最高？",
];

// Last evaluation result
const lastEval = computed(() => {
  for (let i = chat.messages.length - 1; i >= 0; i--) {
    const m = chat.messages[i];
    if (m._eval) return m._eval;
  }
  return null;
});

// Markdown rendering
marked.setOptions({ breaks: true, gfm: true });
function renderMd(t: string) {
  if (!t) return "";
  const raw = marked.parse(t) as string;
  return DOMPurify.sanitize(raw);
}

// Step color class
function stepColorClass(agent: string | undefined) {
  if (!agent) return "";
  if (agent.includes("Planner") || agent.includes("Validator")) return "deep";
  if (agent.includes("SQL") || agent.includes("tools_sql")) return "sql";
  if (agent.includes("Chart") || agent.includes("tools_chart")) return "chart";
  if (agent.includes("Report")) return "report";
  if (agent.includes("Optimistic") || agent.includes("Pessimistic")) return "debate";
  return "";
}

function isLastStep(id: string | undefined) {
  if (!id) return false;
  const steps = chat.messages.filter(m => m.type === "step");
  return steps.length > 0 && steps[steps.length - 1].id === id;
}

function submit() {
  const q = input.value.trim();
  if (!q || chat.isProcessing) return;
  input.value = "";
  send(q);
}

function quick(q: string) { input.value = q; submit(); }

function autoResize() {
  const el = inputEl.value;
  if (el) { el.style.height = "auto"; el.style.height = Math.min(el.scrollHeight, 120) + "px"; }
}

watch(() => chat.messages.length, () => {
  nextTick(() => {
    if (scrollEl.value) scrollEl.value.scrollTop = scrollEl.value.scrollHeight;
  });
});
</script>

<style scoped>
.chat-shell {
  display: flex;
  flex-direction: column;
  height: 100%;
}

/* ─── Header ─── */
.chat-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 28px;
  border-bottom: 1px solid var(--stone-border);
  background: var(--stone-surface);
  flex-shrink: 0;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.stage-badge {
  font-size: 12px;
  color: var(--accent);
  font-weight: 520;
}

.stage-idle {
  font-size: 12px;
  color: var(--ink-tertiary);
}

.header-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.eval-badge {
  font-size: 11px;
  font-family: var(--font-mono);
  padding: 3px 8px;
  border-radius: 99px;
  background: var(--accent-bg);
  color: var(--accent);
  font-weight: 550;
}

.eval-badge.fail {
  background: var(--amber-bg);
  color: var(--amber);
}

.clear-btn {
  font-size: 12px;
  color: var(--ink-tertiary);
  background: none;
  border: none;
  cursor: pointer;
  padding: 4px;
  transition: color var(--duration-fast);
}

.clear-btn:hover { color: var(--red); }

/* ─── Body ─── */
.chat-body {
  flex: 1;
  overflow-y: auto;
  padding: 28px 32px;
}

.chat-body.empty-state {
  display: flex;
  align-items: center;
  justify-content: center;
}

/* ─── User bubble ─── */
.msg-row.user {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 24px;
}

.user-bubble {
  background: var(--ink-primary);
  color: #fff;
  padding: 10px 18px;
  border-radius: 14px 14px 4px 14px;
  max-width: 58%;
  font-size: 14px;
  line-height: 1.55;
}

/* ─── Step timeline ─── */
.step-row {
  display: flex;
  gap: 12px;
  padding: 5px 0;
}

.step-indicator {
  display: flex;
  flex-direction: column;
  align-items: center;
  flex-shrink: 0;
  width: 20px;
}

.step-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
  background: var(--ink-tertiary);
  margin-top: 4px;
}

.step-dot.deep  { background: var(--purple); }
.step-dot.sql   { background: var(--blue); }
.step-dot.chart { background: var(--accent); }
.step-dot.report { background: var(--amber); }
.step-dot.debate { background: var(--amber); }

.step-line {
  width: 1px;
  flex: 1;
  background: var(--stone-border);
  margin-top: 4px;
}

.step-content {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.step-agent {
  font-size: 10.5px;
  font-weight: 600;
  color: var(--ink-tertiary);
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.step-msg {
  font-size: 13px;
  color: var(--ink-secondary);
  word-break: break-word;
}

.token-stream {
  font-size: 13px;
  color: var(--ink-primary);
  font-family: var(--font-mono);
  background: var(--stone-hover);
  padding: 3px 6px;
  border-radius: 4px;
  margin-top: 4px;
  white-space: pre-wrap;
}

.cursor-blink {
  animation: blink 1s step-end infinite;
  color: var(--accent);
  font-weight: 300;
}

@keyframes blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0; }
}

/* ─── SQL block ─── */
.sql-block {
  margin: 10px 0 10px 32px;
  background: var(--stone-bg);
  border: 1px solid var(--stone-border);
  border-radius: var(--radius-md);
  overflow: hidden;
}

.sql-header {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 8px 14px;
  background: var(--stone-hover);
  border-bottom: 1px solid var(--stone-border);
  font-size: 11px;
  font-weight: 550;
  color: var(--ink-secondary);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.sql-block pre {
  padding: 14px 16px;
  margin: 0;
  overflow-x: auto;
  font-family: var(--font-mono);
  font-size: 12.5px;
  line-height: 1.6;
  color: var(--ink-primary);
}

.sql-block code {
  font-family: var(--font-mono);
}

/* ─── Debate cards ─── */
.debate-card {
  margin: 14px 0 14px 32px;
  padding: 16px 18px;
  border-radius: var(--radius-md);
  font-size: 13px;
  line-height: 1.65;
  background: var(--stone-surface);
  border: 1px solid var(--stone-border);
}

.debate-card.opt {
  border-left: 3px solid var(--accent);
  background: var(--accent-bg);
}

.debate-card.pess {
  border-left: 3px solid var(--amber);
  background: var(--amber-bg);
}

.debate-header {
  margin-bottom: 8px;
}

.debate-label {
  font-size: 11.5px;
  font-weight: 600;
  letter-spacing: 0.03em;
}

.opt .debate-label { color: var(--accent); }
.pess .debate-label { color: var(--amber); }

.debate-body {
  color: var(--ink-secondary);
}

/* ─── Debate scores ─── */
.score-row {
  display: flex;
  align-items: center;
  gap: 0;
  margin: 12px 0 16px 32px;
  padding: 12px 20px;
  background: var(--stone-surface);
  border: 1px solid var(--stone-border);
  border-radius: var(--radius-md);
}

.score-card {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
}

.score-value {
  font-size: 28px;
  font-weight: 700;
  font-family: var(--font-mono);
  letter-spacing: -0.02em;
}

.opt-score .score-value { color: var(--accent); }
.pess-score .score-value { color: var(--amber); }

.score-label {
  font-size: 10.5px;
  color: var(--ink-tertiary);
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.score-divider {
  padding: 0 24px;
}

.score-winner {
  font-size: 11px;
  font-weight: 600;
  color: var(--ink-primary);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

/* ─── Chart ─── */
.chart-wrapper {
  margin: 18px 0 18px 32px;
}

/* ─── Report ─── */
.report-card {
  margin: 20px 0;
  padding: 28px 32px;
  background: var(--stone-surface);
  border: 1px solid var(--stone-border);
  border-radius: var(--radius-lg);
  font-size: 14px;
  line-height: 1.8;
  color: var(--ink-primary);
}

.report-body :deep(h1) { font-size: 22px; font-weight: 700; margin: 28px 0 10px; color: var(--ink-primary); letter-spacing: -0.02em; }
.report-body :deep(h2) { font-size: 18px; font-weight: 650; margin: 24px 0 8px; color: var(--ink-primary); letter-spacing: -0.01em; }
.report-body :deep(h3) { font-size: 15px; font-weight: 600; margin: 20px 0 6px; color: var(--ink-primary); }
.report-body :deep(h4) { font-size: 14px; font-weight: 600; margin: 16px 0 6px; color: var(--ink-secondary); }
.report-body :deep(p) { margin: 8px 0; }
.report-body :deep(strong) { font-weight: 600; color: var(--ink-primary); }
.report-body :deep(ul), .report-body :deep(ol) { padding-left: 20px; margin: 8px 0; }
.report-body :deep(li) { margin: 4px 0; }
.report-body :deep(code) {
  font-family: var(--font-mono);
  font-size: 12.5px;
  background: var(--stone-hover);
  padding: 2px 6px;
  border-radius: 4px;
  border: 1px solid var(--stone-border);
}
.report-body :deep(pre) {
  background: var(--stone-bg);
  border: 1px solid var(--stone-border);
  border-radius: var(--radius-md);
  padding: 16px;
  overflow-x: auto;
  margin: 12px 0;
}
.report-body :deep(pre code) {
  background: none;
  border: none;
  padding: 0;
}
.report-body :deep(table) {
  width: 100%;
  border-collapse: collapse;
  margin: 14px 0;
  font-size: 13px;
}
.report-body :deep(th) {
  background: var(--stone-hover);
  padding: 10px 14px;
  text-align: left;
  font-weight: 600;
  border-bottom: 2px solid var(--stone-border);
  color: var(--ink-secondary);
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.report-body :deep(td) {
  padding: 8px 14px;
  border-bottom: 1px solid var(--stone-border);
  font-family: var(--font-mono);
  font-size: 12.5px;
}
.report-body :deep(blockquote) {
  border-left: 3px solid var(--accent);
  padding: 8px 16px;
  margin: 12px 0;
  color: var(--ink-secondary);
  background: var(--accent-bg);
  border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
}

/* ─── Empty state ─── */
.empty-inner {
  text-align: center;
  max-width: 460px;
}

.empty-icon {
  color: var(--ink-tertiary);
  margin-bottom: 20px;
  opacity: 0.5;
}

.empty-heading {
  font-size: 22px;
  font-weight: 700;
  margin-bottom: 8px;
  color: var(--ink-primary);
  letter-spacing: -0.02em;
}

.empty-desc {
  font-size: 14px;
  color: var(--ink-secondary);
  margin-bottom: 28px;
  line-height: 1.6;
  max-width: 380px;
  margin-left: auto;
  margin-right: auto;
}

.quick-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: center;
}

.quick-chip {
  font-size: 12px;
  padding: 8px 16px;
  border: 1px solid var(--stone-border);
  border-radius: 99px;
  background: var(--stone-surface);
  cursor: pointer;
  color: var(--ink-secondary);
  transition: all var(--duration-fast) var(--ease-out-expo);
  font-family: var(--font-sans);
}

.quick-chip:hover {
  border-color: var(--accent);
  color: var(--accent);
  background: var(--accent-bg);
}

.quick-chip:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

/* ─── Footer / Input ─── */
.chat-footer {
  padding: 14px 28px;
  border-top: 1px solid var(--stone-border);
  background: var(--stone-surface);
  flex-shrink: 0;
}

.input-wrap {
  display: flex;
  gap: 10px;
  align-items: flex-end;
}

.input-wrap textarea {
  flex: 1;
  border: 1px solid var(--stone-border);
  border-radius: var(--radius-lg);
  padding: 10px 16px;
  font-size: 14px;
  resize: none;
  outline: none;
  font-family: var(--font-sans);
  line-height: 1.5;
  background: var(--stone-bg);
  color: var(--ink-primary);
  transition: border-color var(--duration-fast) var(--ease-out-expo);
}

.input-wrap textarea:focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px rgba(5, 150, 105, 0.08);
}

.input-wrap textarea::placeholder {
  color: var(--ink-tertiary);
}

.send-btn {
  width: 40px;
  height: 40px;
  border-radius: var(--radius-md);
  background: var(--ink-primary);
  color: #fff;
  border: none;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: all var(--duration-fast) var(--ease-out-expo);
}

.send-btn:hover {
  background: var(--accent);
}

.send-btn:active {
  transform: scale(0.96);
}

.send-btn:disabled {
  background: var(--ink-tertiary);
  cursor: not-allowed;
  transform: none;
}
</style>
