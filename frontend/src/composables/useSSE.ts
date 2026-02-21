/**
 * SSE 流式对话 Composable
 *
 * 参考: smart-qa-agent-system/frontend/src/composables/useSSE.ts
 *
 * 封装 SSE 连接、事件解析、状态更新逻辑
 */
import { ref, onUnmounted } from "vue";
import { useChatStore } from "@/stores/chat";

export function useSSE() {
  const chat = useChatStore();
  const controller = ref<AbortController | null>(null);

  async function send(query: string) {
    if (chat.isProcessing) return;

    chat.addUserMessage(query);
    chat.startStreaming();

    const abort = new AbortController();
    controller.value = abort;

    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query, tables: chat.tables }),
        signal: abort.signal,
      });

      if (!response.ok) {
        const err = await response.json().catch(() => ({ detail: "请求失败" }));
        chat.setError(err.detail || `HTTP ${response.status}`);
        return;
      }

      const reader = response.body?.getReader();
      if (!reader) {
        chat.setError("无法读取响应流");
        return;
      }

      const decoder = new TextDecoder();
      let buffer = "";
      let eventType = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (line.startsWith("event: ")) {
            eventType = line.slice(7).trim();
          } else if (line.startsWith("data: ")) {
            try {
              const data = JSON.parse(line.slice(6));
              handleEvent(eventType, data);
            } catch {
              // 忽略解析错误
            }
          }
        }
      }
    } catch (err: any) {
      if (err.name !== "AbortError") {
        chat.setError(err.message || "连接失败");
      }
    }
  }

  function handleEvent(event: string, data: any) {
    switch (event) {
      case "step":
        chat.addStep(data.agent || "Agent", data.progress || "", data.agentLabel);
        break;
      case "debate":
        chat.addDebate(data.agent || "", data.content || "");
        break;
      case "chart":
        if (data.chart_json) chat.addChart(data.chart_json);
        break;
      case "sql":
        if (data.queries) chat.addSQL(data.queries);
        break;
      case "report":
        chat.addReport(data.content || data.final_report || "");
        break;
      case "done":
        chat.finishAnalysis(data.final_report || "", data.agents || null);
        break;
      case "error":
        chat.setError(data.message || "未知错误");
        break;
    }
  }

  function abort() {
    controller.value?.abort();
    controller.value = null;
    chat.isProcessing = false;
  }

  onUnmounted(() => abort());

  return { send, abort, isProcessing: chat.isProcessing };
}
