<template>
  <div class="analysis-layout">
    <!-- Left: Chat timeline -->
    <div class="chat-zone">
      <div class="chat-shell">
        <header class="chat-header">
          <div class="header-left">
            <span class="stage-badge" v-if="chat.isProcessing">{{ chat.currentStage }}</span>
            <span class="stage-idle" v-else>就绪</span>
          </div>
          <div class="header-right">
            <span class="token-stat" v-if="totalSteps > 0">
              {{ totalSteps }} 步骤
            </span>
            <button class="clear-btn" @click="chat.clearMessages()" v-if="chat.messages.length">清除</button>
          </div>
        </header>

        <!-- Chat messages -->
        <div ref="scrollEl" class="chat-body" v-if="chat.messages.length">
          <template v-for="(msg, idx) in chat.messages" :key="msg.id">
            <!-- User message -->
            <Transition name="msg-slide">
              <div v-if="msg.role === 'user'" class="msg-row user">
                <div class="user-bubble">{{ msg.content }}</div>
              </div>
            </Transition>

            <!-- Step timeline -->
            <Transition name="step-fade">
              <div v-if="msg.type === 'step'" class="step-row">
                <div class="step-indicator">
                  <span class="step-dot" :class="stepColor(msg.agent)"></span>
                  <span class="step-line" v-if="!isLastStep(msg.id)"></span>
                </div>
                <div class="step-content">
                  <span class="step-agent">{{ msg.agentLabel || msg.agent }}</span>
                  <span class="step-msg">{{ msg.content }}</span>
                  <span
                    v-if="chat.currentStreamingAgent === msg.agent && chat.streamingTokens[msg.agent]"
                    class="token-stream"
                  >{{ chat.streamingTokens[msg.agent] }}<span class="cursor-blink">|</span></span>
                </div>
              </div>
            </Transition>

            <!-- SQL block -->
            <Transition name="fade-up">
              <div v-if="msg.type === 'sql'" class="sql-block">
                <div class="sql-header">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>
                  <span>SQL 查询</span>
                </div>
                <pre><code>{{ msg.content }}</code></pre>
              </div>
            </Transition>

            <!-- Debate cards -->
            <Transition name="fade-up">
              <div v-if="msg.type === 'debate'" class="debate-card" :class="msg.agent === 'Optimistic' ? 'opt' : 'pess'">
                <div class="debate-header">
                  <span class="debate-label">{{ msg.agent === 'Optimistic' ? '乐观视角' : '谨慎视角' }}</span>
                </div>
                <div class="debate-body">{{ msg.content?.slice(0, 400) }}{{ msg.content?.length > 400 ? '...' : '' }}</div>
              </div>
            </Transition>

            <!-- Chart (inline) -->
            <Transition name="fade-up">
              <div v-if="msg.type === 'chart'" class="chart-inline">
                <ChartCard :chart-json="msg.chartJson" />
              </div>
            </Transition>

            <!-- Token stream for final LLM output -->
            <Transition name="fade-up">
              <div
                v-if="msg.isStreaming && chat.streamingTokens['llm']"
                class="stream-block"
              >{{ chat.streamingTokens['llm'] }}<span class="cursor-blink">|</span></div>
            </Transition>
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
            <p class="empty-desc">7 个 AI Agent 协作，自动产出带交互式图表的分析报告</p>
            <div class="quick-row">
              <button v-for="q in prompts" :key="q" @click="quick(q)" :disabled="chat.isProcessing" class="quick-chip">
                {{ q }}
              </button>
            </div>
          </div>
        </div>

        <!-- Input -->
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
    </div>

    <!-- Right: Dashboard + Report -->
    <aside class="insight-zone">
      <AgentDashboard />
      <div class="insight-spacer"></div>
      <ReportPanel />
    </aside>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, nextTick, computed } from "vue";
import { useChatStore } from "@/stores/chat";
import { useSSE } from "@/composables/useSSE";
import ChartCard from "@/components/ChartCard.vue";
import AgentDashboard from "@/components/AgentDashboard.vue";
import ReportPanel from "@/components/ReportPanel.vue";

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

const totalSteps = computed(() =>
  chat.messages.filter((m) => m.type === "step").length
);

function stepColor(agent: string | undefined) {
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
  const steps = chat.messages.filter((m) => m.type === "step");
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

watch(
  () => chat.messages.length,
  () => {
    nextTick(() => {
      if (scrollEl.value) scrollEl.value.scrollTop = scrollEl.value.scrollHeight;
    });
  }
);
</script>

<style scoped>
.analysis-layout {
  display: flex;
  height: 100%;
  gap: 0;
  overflow: hidden;
}

/* ─── Chat Zone ─── */
.chat-zone {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  border-right: 1px solid var(--stone-border);
}

.chat-shell {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.chat-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 24px;
  border-bottom: 1px solid var(--stone-border);
  background: var(--stone-surface);
  flex-shrink: 0;
}

.header-left { display: flex; align-items: center; gap: 10px; }
.stage-badge { font-size: 12px; color: var(--accent); font-weight: 520; }
.stage-idle { font-size: 12px; color: var(--ink-tertiary); }

.header-right { display: flex; align-items: center; gap: 12px; }
.token-stat { font-size: 11px; font-family: var(--font-mono); color: var(--ink-tertiary); }

.clear-btn {
  font-size: 12px; color: var(--ink-tertiary); background: none; border: none;
  cursor: pointer; padding: 4px; transition: color var(--duration-fast);
}
.clear-btn:hover { color: var(--red); }

/* ─── Chat Body ─── */
.chat-body {
  flex: 1;
  overflow-y: auto;
  padding: 24px 28px;
  scroll-behavior: smooth;
}

.chat-body.empty-state {
  display: flex;
  align-items: center;
  justify-content: center;
}

/* ─── User ─── */
.msg-row.user { display: flex; justify-content: flex-end; margin-bottom: 20px; }
.user-bubble {
  background: var(--ink-primary); color: #fff; padding: 10px 18px;
  border-radius: 14px 14px 4px 14px; max-width: 58%; font-size: 14px; line-height: 1.55;
}

/* ─── Steps ─── */
.step-row { display: flex; gap: 12px; padding: 5px 0; }
.step-indicator { display: flex; flex-direction: column; align-items: center; flex-shrink: 0; width: 20px; }
.step-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; background: var(--ink-tertiary); margin-top: 4px; }
.step-dot.deep  { background: var(--purple); }
.step-dot.sql   { background: var(--blue); }
.step-dot.chart { background: var(--accent); }
.step-dot.report { background: var(--amber); }
.step-dot.debate { background: var(--amber); }
.step-line { width: 1px; flex: 1; background: var(--stone-border); margin-top: 4px; }
.step-content { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.step-agent { font-size: 10.5px; font-weight: 600; color: var(--ink-tertiary); text-transform: uppercase; letter-spacing: 0.06em; }
.step-msg { font-size: 13px; color: var(--ink-secondary); word-break: break-word; }
.token-stream { font-size: 13px; color: var(--ink-primary); font-family: var(--font-mono); background: var(--stone-hover); padding: 3px 6px; border-radius: 4px; margin-top: 4px; white-space: pre-wrap; }
.cursor-blink { animation: blink 1s step-end infinite; color: var(--accent); font-weight: 300; }
@keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: 0; } }

/* ─── SQL ─── */
.sql-block { margin: 10px 0 10px 32px; background: var(--stone-bg); border: 1px solid var(--stone-border); border-radius: var(--radius-md); overflow: hidden; }
.sql-header { display: flex; align-items: center; gap: 7px; padding: 8px 14px; background: var(--stone-hover); border-bottom: 1px solid var(--stone-border); font-size: 11px; font-weight: 550; color: var(--ink-secondary); text-transform: uppercase; letter-spacing: 0.04em; }
.sql-block pre { padding: 14px 16px; margin: 0; overflow-x: auto; font-family: var(--font-mono); font-size: 12.5px; line-height: 1.6; color: var(--ink-primary); }

/* ─── Debate ─── */
.debate-card { margin: 14px 0 14px 32px; padding: 16px 18px; border-radius: var(--radius-md); font-size: 13px; line-height: 1.65; background: var(--stone-surface); border: 1px solid var(--stone-border); }
.debate-card.opt { border-left: 3px solid var(--accent); background: var(--accent-bg); }
.debate-card.pess { border-left: 3px solid var(--amber); background: var(--amber-bg); }
.debate-header { margin-bottom: 8px; }
.debate-label { font-size: 11.5px; font-weight: 600; letter-spacing: 0.03em; }
.opt .debate-label { color: var(--accent); }
.pess .debate-label { color: var(--amber); }
.debate-body { color: var(--ink-secondary); }

/* ─── Chart inline ─── */
.chart-inline { margin: 18px 0 18px 32px; }

/* ─── Empty state ─── */
.empty-inner { text-align: center; max-width: 460px; }
.empty-icon { color: var(--ink-tertiary); margin-bottom: 20px; opacity: 0.5; }
.empty-heading { font-size: 22px; font-weight: 700; margin-bottom: 8px; color: var(--ink-primary); letter-spacing: -0.02em; }
.empty-desc { font-size: 14px; color: var(--ink-secondary); margin-bottom: 28px; line-height: 1.6; max-width: 380px; margin-inline: auto; }
.quick-row { display: flex; flex-wrap: wrap; gap: 8px; justify-content: center; }
.quick-chip {
  font-size: 12px; padding: 8px 16px; border: 1px solid var(--stone-border); border-radius: var(--radius-full);
  background: var(--stone-surface); cursor: pointer; color: var(--ink-secondary);
  transition: all var(--duration-fast); font-family: var(--font-sans);
}
.quick-chip:hover { border-color: var(--accent); color: var(--accent); background: var(--accent-bg); }
.quick-chip:disabled { opacity: 0.4; cursor: not-allowed; }

/* ─── Input ─── */
.chat-footer { padding: 14px 24px; border-top: 1px solid var(--stone-border); background: var(--stone-surface); flex-shrink: 0; }
.input-wrap { display: flex; gap: 10px; align-items: flex-end; }
.input-wrap textarea {
  flex: 1; border: 1px solid var(--stone-border); border-radius: var(--radius-lg); padding: 10px 16px;
  font-size: 14px; resize: none; outline: none; font-family: var(--font-sans); line-height: 1.5;
  background: var(--stone-bg); color: var(--ink-primary);
  transition: border-color var(--duration-fast);
}
.input-wrap textarea:focus { border-color: var(--accent); box-shadow: 0 0 0 3px rgba(5, 150, 105, 0.08); }
.input-wrap textarea::placeholder { color: var(--ink-tertiary); }
.send-btn {
  width: 40px; height: 40px; border-radius: var(--radius-md); background: var(--ink-primary);
  color: #fff; border: none; cursor: pointer; display: flex; align-items: center; justify-content: center;
  flex-shrink: 0; transition: all var(--duration-fast);
}
.send-btn:hover { background: var(--accent); }
.send-btn:active { transform: scale(0.96); }
.send-btn:disabled { background: var(--ink-tertiary); cursor: not-allowed; transform: none; }

/* ─── Insight Zone ─── */
.insight-zone {
  width: 380px;
  min-width: 340px;
  display: flex;
  flex-direction: column;
  gap: var(--panel-gap);
  padding: 16px;
  overflow-y: auto;
  background: var(--stone-bg);
}

.insight-spacer { flex: 0; }

/* ─── Transitions (Taste-Skill inspired micro-animations) ─── */
.msg-slide-enter-active { transition: all var(--duration-slow) var(--ease-spring); }
.msg-slide-enter-from { opacity: 0; transform: translateY(12px); }

.step-fade-enter-active { transition: all var(--duration-normal) var(--ease-out-expo); }
.step-fade-enter-from { opacity: 0; transform: translateX(-8px); }

.fade-up-enter-active { transition: all var(--duration-slow) var(--ease-out-expo); }
.fade-up-enter-from { opacity: 0; transform: translateY(16px); }

/* ─── Responsive ─── */
@media (max-width: 1024px) {
  .insight-zone { width: 320px; min-width: 280px; padding: 10px; }
  .chat-body { padding: 16px 20px; }
}
@media (max-width: 768px) {
  .analysis-layout { flex-direction: column; }
  .insight-zone { width: 100%; min-width: 0; max-height: 40vh; flex-shrink: 0; }
  .chat-zone { border-right: none; }
}
</style>
