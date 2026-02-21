<template>
  <div class="chat-shell">
    <header class="chat-header">
      <div>
        <span class="stage-badge" v-if="chat.isProcessing">{{ chat.currentStage }}</span>
        <span class="stage-idle" v-else>就绪</span>
      </div>
      <button class="clear-btn" @click="chat.clearMessages()" v-if="chat.messages.length">清空</button>
    </header>

    <div ref="scrollEl" class="chat-body" v-if="chat.messages.length">
      <template v-for="msg in chat.messages" :key="msg.id">
        <!-- User -->
        <div v-if="msg.role === 'user'" class="msg-row user">
          <div class="msg-bubble user-bubble">{{ msg.content }}</div>
        </div>

        <!-- Agent Step -->
        <div v-else-if="msg.type === 'step'" class="step-row">
          <span class="step-dot" :class="stepColor(msg.agent)"></span>
          <span class="step-label">{{ msg.agentLabel || msg.agent }}</span>
          <span class="step-msg">{{ msg.content }}</span>
        </div>

        <!-- Debate -->
        <div v-else-if="msg.type === 'debate'" class="debate-card" :class="msg.agent === 'Optimistic' ? 'optimistic' : 'pessimistic'">
          <div class="debate-hdr">
            <span>{{ msg.agent === 'Optimistic' ? '🌱 乐观方' : '🛡️ 谨慎方' }}</span>
          </div>
          <p>{{ msg.content?.slice(0, 400) }}{{ msg.content?.length > 400 ? '...' : '' }}</p>
        </div>

        <!-- Chart -->
        <div v-else-if="msg.type === 'chart'" class="chart-wrapper">
          <ChartCard :chart-json="msg.chartJson" />
        </div>

        <!-- Report -->
        <div v-else-if="msg.type === 'report' || msg.role === 'assistant'" class="report-card">
          <div class="report-body" v-html="renderMd(msg.content)" />
        </div>
      </template>
    </div>

    <!-- Empty -->
    <div class="chat-body empty" v-else>
      <div class="empty-state">
        <div class="empty-icon">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/></svg>
        </div>
        <h2>上传 CSV 开始分析</h2>
        <p>7 个 AI 智能体协作：查询数据、生成图表、正反辩论、裁判验证</p>
        <div class="quick-row">
          <button v-for="q in prompts" :key="q" @click="quick(q)" :disabled="chat.isProcessing">{{ q }}</button>
        </div>
      </div>
    </div>

    <!-- Input -->
    <div class="chat-footer">
      <textarea
        v-model="input" placeholder="输入你的数据分析问题..."
        :disabled="chat.isProcessing" rows="1"
        @keydown.enter.exact.prevent="submit"
        @input="autoResize"
        ref="inputEl"
      ></textarea>
      <button class="send-btn" @click="submit" :disabled="chat.isProcessing || !input.trim()">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="12" y1="19" x2="12" y2="5"/><polyline points="5 12 12 5 19 12"/></svg>
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, nextTick } from "vue";
import { useChatStore } from "@/stores/chat";
import { useSSE } from "@/composables/useSSE";
import ChartCard from "@/components/ChartCard.vue";

const chat = useChatStore();
const { send } = useSSE();
const input = ref("");
const scrollEl = ref<HTMLElement>();
const inputEl = ref<HTMLTextAreaElement>();

const prompts = [
  "销量和好评率最高的5个品牌？",
  "高折扣率真的能带来高销量吗？",
  "综合考虑价格、好评率、保修期，哪个品牌性价比最高？",
];

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
function stepColor(agent: string) {
  if (agent?.includes("Planner") || agent?.includes("Validator")) return "deep";
  if (agent?.includes("SQL") || agent?.includes("tools_sql")) return "sql";
  if (agent?.includes("Chart") || agent?.includes("tools_chart")) return "chart";
  if (agent?.includes("Report")) return "report";
  if (agent?.includes("Optimistic") || agent?.includes("Pessimistic")) return "debate";
  return "";
}
function renderMd(t: string) {
  if (!t) return "";
  let html = t
    .replace(/### (.+)/g, "<h4>$1</h4>")
    .replace(/## (.+)/g, "<h3>$1</h3>")
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\n\n/g, "<br><br>")
    .replace(/^- (.+)/gm, "&bull; $1");
  // Markdown table -> HTML table
  html = html.replace(/(\|[^\n]+\|[\s\S]*?)(?=\n\n|\n*$)/g, (match) => {
    const lines = match.trim().split("\n").filter(l => l.includes("|"));
    if (lines.length < 2) return match;
    const sep = lines[1];
    if (!/^[\|\s\-:]+$/.test(sep)) return match;
    let table = '<table class="md-table"><thead><tr>';
    lines[0].split("|").filter(c => c.trim()).forEach(c => table += `<th>${c.trim()}</th>`);
    table += '</tr></thead><tbody>';
    for (let i = 2; i < lines.length; i++) {
      table += '<tr>';
      lines[i].split("|").filter(c => c.trim()).forEach(c => table += `<td>${c.trim()}</td>`);
      table += '</tr>';
    }
    return table + '</tbody></table>';
  });
  return html;
}
watch(() => chat.messages.length, () => nextTick(() => { if (scrollEl.value) scrollEl.value.scrollTop = scrollEl.value.scrollHeight; }));
</script>

<style scoped>
.chat-shell { display: flex; flex-direction: column; height: 100%; }
.chat-header { display: flex; align-items: center; justify-content: space-between; padding: 10px 24px; border-bottom: 1px solid #e5e7eb; background: #fff; flex-shrink: 0; }
.stage-badge { font-size: 12px; color: var(--emerald); font-weight: 500; }
.stage-idle { font-size: 12px; color: #94a3b8; }
.clear-btn { font-size: 12px; color: #94a3b8; background: none; border: none; cursor: pointer; }
.clear-btn:hover { color: var(--red); }

.chat-body { flex: 1; overflow-y: auto; padding: 20px 24px; }
.chat-body.empty { display: flex; align-items: center; justify-content: center; }

/* User bubble */
.msg-row.user { display: flex; justify-content: flex-end; margin-bottom: 20px; }
.user-bubble { background: var(--slate-900); color: #fff; padding: 10px 16px; border-radius: 18px 18px 4px 18px; max-width: 65%; font-size: 14px; line-height: 1.5; }

/* Step timeline */
.step-row { display: flex; align-items: center; gap: 8px; padding: 6px 0; }
.step-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; background: #cbd5e1; }
.step-dot.deep { background: #8b5cf6; }
.step-dot.sql { background: #3b82f6; }
.step-dot.chart { background: var(--emerald); }
.step-dot.report { background: #f59e0b; }
.step-dot.debate { background: var(--amber); }
.step-label { font-size: 11px; font-weight: 600; color: #64748b; text-transform: uppercase; letter-spacing: 0.5px; flex-shrink: 0; min-width: 72px; }
.step-msg { font-size: 13px; color: #475569; white-space: pre-wrap; word-break: break-all; }
.step-msg.sql-content { font-family: "SF Mono", "Fira Code", monospace; font-size: 11px; background: #f8fafc; padding: 8px 12px; border-radius: 6px; display: block; margin-top: 4px; color: #334155; max-height: 200px; overflow-y: auto; }

/* Debate cards */
.debate-card { margin: 12px 0; padding: 14px 16px; border-radius: var(--radius); font-size: 13px; line-height: 1.6; }
.debate-card.optimistic { background: var(--emerald-bg); border-left: 3px solid var(--emerald); }
.debate-card.pessimistic { background: var(--amber-bg); border-left: 3px solid var(--amber); }
.debate-hdr { font-weight: 600; font-size: 12px; margin-bottom: 6px; }
.debate-card.optimistic .debate-hdr { color: var(--emerald); }
.debate-card.pessimistic .debate-hdr { color: var(--amber); }

/* Chart */
.chart-wrapper { margin: 16px 0; }

/* Report */
.report-card { margin: 16px 0; padding: 20px 24px; background: #fff; border: 1px solid #e5e7eb; border-radius: var(--radius); font-size: 14px; line-height: 1.8; }
.report-body :deep(h3) { font-size: 16px; margin: 20px 0 8px; color: var(--slate-900); }
.report-body :deep(h4) { font-size: 14px; margin: 14px 0 6px; color: #334155; }
.report-body :deep(strong) { color: var(--slate-900); }
.report-body :deep(.md-table) { width: 100%; border-collapse: collapse; margin: 12px 0; font-size: 13px; }
.report-body :deep(.md-table th) { background: var(--slate-100); padding: 8px 12px; text-align: left; font-weight: 600; border-bottom: 2px solid #e5e7eb; }
.report-body :deep(.md-table td) { padding: 6px 12px; border-bottom: 1px solid #f1f5f9; }

/* Empty */
.empty-state { text-align: center; max-width: 420px; }
.empty-icon { color: #cbd5e1; margin-bottom: 16px; }
.empty-state h2 { font-size: 20px; font-weight: 700; margin-bottom: 8px; color: var(--slate-900); }
.empty-state p { font-size: 14px; color: #64748b; margin-bottom: 24px; line-height: 1.6; }
.quick-row { display: flex; flex-wrap: wrap; gap: 8px; justify-content: center; }
.quick-row button { font-size: 12px; padding: 8px 14px; border: 1px solid #e5e7eb; border-radius: 20px; background: #fff; cursor: pointer; color: #475569; transition: all .15s; }
.quick-row button:hover { border-color: var(--emerald); color: var(--emerald); background: var(--emerald-bg); }

/* Footer */
.chat-footer { padding: 12px 24px; border-top: 1px solid #e5e7eb; display: flex; gap: 10px; align-items: flex-end; background: #fff; flex-shrink: 0; }
.chat-footer textarea { flex: 1; border: 1px solid #e5e7eb; border-radius: 12px; padding: 10px 14px; font-size: 14px; resize: none; outline: none; font-family: inherit; line-height: 1.5; transition: border-color .15s; }
.chat-footer textarea:focus { border-color: var(--emerald); }
.send-btn { width: 40px; height: 40px; border-radius: 50%; background: var(--slate-900); color: #fff; border: none; cursor: pointer; display: flex; align-items: center; justify-content: center; flex-shrink: 0; transition: background .15s; }
.send-btn:hover { background: var(--emerald); }
.send-btn:disabled { background: #cbd5e1; cursor: not-allowed; }

</style>
