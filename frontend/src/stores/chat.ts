import { defineStore } from "pinia";
import { ref, computed } from "vue";

export interface ChatMessage {
  id: string; role: "user" | "assistant" | "system"; content: string;
  type?: "step" | "debate" | "chart" | "report";
  agent?: string; agentLabel?: string; chartJson?: any; timestamp: number; isStreaming?: boolean;
}

const AGENT_LABELS: Record<string, string> = {
  "Planner": "任务规划", "SQL Agent": "数据查询", "tools_sql": "执行SQL",
  "Chart Agent": "生成图表", "tools_chart": "渲染图表",
  "Msg Clear SQL": "整理上下文", "Msg Clear Chart": "整理上下文",
  "Report Agent": "撰写报告", "Optimistic": "乐观方辩论", "Pessimistic": "谨慎方辩论", "Validator": "裁判验证",
};

export const useChatStore = defineStore("chat", () => {
  const messages = ref<ChatMessage[]>([]);
  const agentResults = ref<any>(null);
  const isProcessing = ref(false);
  const currentStage = ref("就绪");
  const error = ref("");
  const tables = ref<string[]>([]);
  const storeReady = ref(false);

  const lastAssistantMsg = computed(() => {
    for (let i = messages.value.length - 1; i >= 0; i--)
      if (messages.value[i].role === "assistant") return messages.value[i];
    return null;
  });

  function addUserMessage(content: string) {
    messages.value.push({ id: crypto.randomUUID(), role: "user", content, timestamp: Date.now() });
  }
  function startStreaming(): string {
    isProcessing.value = true; error.value = ""; currentStage.value = "分析中...";
    const id = crypto.randomUUID();
    messages.value.push({ id, role: "assistant", content: "", timestamp: Date.now(), isStreaming: true });
    return id;
  }
  function addStep(agent: string, progress: string, agentLabel?: string) {
    const label = agentLabel || AGENT_LABELS[agent] || agent;
    currentStage.value = `${label}: ${progress}`;
    messages.value.push({ id: crypto.randomUUID(), role: "system", type: "step", agent, agentLabel: label, content: progress, timestamp: Date.now() });
  }
  function addDebate(agent: string, content: string) {
    messages.value.push({ id: crypto.randomUUID(), role: "system", type: "debate", agent, content, timestamp: Date.now() });
  }
  function addChart(json: any) {
    messages.value.push({ id: crypto.randomUUID(), role: "system", type: "chart", content: "", chartJson: json, timestamp: Date.now() });
  }
  function addReport(content: string) {
    messages.value.push({ id: crypto.randomUUID(), role: "assistant", type: "report", content, timestamp: Date.now(), isStreaming: false });
  }
  function finishAnalysis(report: string, agents: any) {
    if (report) addReport(report);
    agentResults.value = agents;
    isProcessing.value = false;
    currentStage.value = "完成";
  }
  function setError(err: string) { error.value = err; isProcessing.value = false; currentStage.value = "错误"; }
  function clearMessages() { messages.value = []; agentResults.value = null; error.value = ""; currentStage.value = "就绪"; }
  function setTables(t: string[]) { tables.value = t; storeReady.value = true; }

  return {
    messages, agentResults, isProcessing, currentStage, error, tables, storeReady, lastAssistantMsg,
    addUserMessage, startStreaming, addStep, addDebate, addChart, addReport, finishAnalysis, setError, clearMessages, setTables,
  };
});
