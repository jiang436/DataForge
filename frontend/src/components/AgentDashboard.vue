<template>
  <div class="dashboard" v-if="agents.length">
    <div class="dashboard-header">
      <span class="dash-title">执行进度</span>
      <span class="dash-stats">
        {{ completedCount }}/{{ agents.length }}
        <span class="dash-elapsed" v-if="elapsed">{{ elapsed }}</span>
      </span>
    </div>
    <div class="agent-list">
      <div
        v-for="agent in agents"
        :key="agent.name"
        class="agent-row"
        :class="agent.status"
      >
        <div class="agent-status-indicator">
          <span class="status-icon" v-if="agent.status === 'completed'">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>
          </span>
          <span class="status-spinner" v-else-if="agent.status === 'in_progress'">
            <span class="spinner-ring"></span>
          </span>
          <span class="status-dot" v-else></span>
        </div>
        <div class="agent-info">
          <span class="agent-name">{{ agent.label }}</span>
          <span class="agent-detail" v-if="agent.detail">{{ agent.detail }}</span>
        </div>
        <span class="agent-time" v-if="agent.elapsed">{{ agent.elapsed }}s</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch, onUnmounted } from "vue";
import { useChatStore } from "@/stores/chat";

const chat = useChatStore();

interface AgentStatus {
  name: string;
  label: string;
  status: "pending" | "in_progress" | "completed" | "error";
  detail?: string;
  elapsed?: number;
}

// Fixed agent order
const AGENT_ORDER = [
  { name: "Planner", label: "任务规划" },
  { name: "SQL Agent", label: "数据查询" },
  { name: "Chart Agent", label: "图表生成" },
  { name: "Report Agent", label: "撰写报告" },
  { name: "Optimistic", label: "乐观方辩论" },
  { name: "Pessimistic", label: "谨慎方辩论" },
  { name: "Validator", label: "裁判验证" },
];

const agents = ref<AgentStatus[]>(
  AGENT_ORDER.map((a) => ({ ...a, status: "pending" as const }))
);

const startTime = ref<number>(0);
const elapsed = ref("");

let timer: ReturnType<typeof setInterval> | null = null;

watch(
  () => chat.isProcessing,
  (processing) => {
    if (processing) {
      startTime.value = Date.now();
      agents.value = AGENT_ORDER.map((a) => ({
        ...a,
        status: "pending" as const,
        detail: undefined,
        elapsed: undefined,
      }));
      timer = setInterval(() => {
        const secs = Math.floor((Date.now() - startTime.value) / 1000);
        elapsed.value = `${Math.floor(secs / 60)}:${String(secs % 60).padStart(2, "0")}`;
      }, 1000);
    } else {
      if (timer) { clearInterval(timer); timer = null; }
    }
  }
);

// Update status based on SSE step events
watch(
  () => chat.messages.length,
  () => {
    if (!chat.isProcessing && !chat.currentStage) return;

    const stepMsgs = chat.messages.filter((m) => m.type === "step");
    const seenAgents = new Set<string>();
    let lastInProgress = "";

    // Find which agents have appeared
    for (const msg of stepMsgs) {
      const agentName = msg.agent || "";
      // Map step agent names to our agent list
      for (const a of agents.value) {
        if (agentName.includes(a.name) || a.name.includes(agentName)) {
          seenAgents.add(a.name);
          lastInProgress = a.name;
        }
      }
    }

    // If processing has stopped, mark all as completed
    if (!chat.isProcessing) {
      agents.value.forEach((a) => {
        a.status = seenAgents.has(a.name) ? "completed" : "pending";
      });
      return;
    }

    // Mark seen agents as completed, current as in_progress
    agents.value.forEach((a) => {
      if (a.name === lastInProgress && chat.isProcessing) {
        a.status = "in_progress";
      } else if (seenAgents.has(a.name)) {
        a.status = "completed";
      }
    });
  },
  { deep: true }
);

// Update current agent detail from stage text
watch(
  () => chat.currentStage,
  (stage) => {
    if (!stage) return;
    for (const a of agents.value) {
      if (a.status === "in_progress") {
        a.detail = stage;
        break;
      }
    }
  }
);

const completedCount = computed(
  () => agents.value.filter((a) => a.status === "completed").length
);

onUnmounted(() => {
  if (timer) clearInterval(timer);
});
</script>

<style scoped>
.dashboard {
  background: var(--stone-surface);
  border: 1px solid var(--stone-border);
  border-radius: var(--radius-lg);
  overflow: hidden;
}

.dashboard-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid var(--stone-border);
  background: var(--stone-hover);
}

.dash-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--ink-primary);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.dash-stats {
  font-size: 11px;
  font-family: var(--font-mono);
  color: var(--ink-secondary);
}

.dash-elapsed {
  margin-left: 8px;
  color: var(--accent);
}

.agent-list {
  padding: 4px 0;
}

.agent-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 16px;
  transition: background var(--duration-fast);
}

.agent-row:hover {
  background: var(--stone-hover);
}

.agent-row.completed {
  opacity: 0.7;
}

.agent-row.in_progress {
  background: var(--accent-bg);
}

.agent-row.error {
  background: var(--red-bg);
}

.agent-status-indicator {
  flex-shrink: 0;
  width: 18px;
  height: 18px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.status-icon {
  color: var(--accent);
}

.status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--ink-tertiary);
}

.spinner-ring {
  display: block;
  width: 12px;
  height: 12px;
  border: 2px solid var(--accent-border);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: dash-spin 0.8s linear infinite;
}

@keyframes dash-spin {
  to { transform: rotate(360deg); }
}

.agent-info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.agent-name {
  font-size: 13px;
  font-weight: 500;
  color: var(--ink-primary);
}

.agent-row.completed .agent-name {
  color: var(--ink-secondary);
}

.agent-row.in_progress .agent-name {
  color: var(--accent);
  font-weight: 600;
}

.agent-detail {
  font-size: 11px;
  color: var(--ink-tertiary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.agent-time {
  font-size: 11px;
  font-family: var(--font-mono);
  color: var(--ink-tertiary);
  flex-shrink: 0;
}
</style>
