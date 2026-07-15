/**
 * SSE 流式对话 Composable
 *
 * 参考: smart-qa-agent-system/frontend/src/composables/useSSE.ts
 *
 * 封装 SSE 连接、事件解析、状态更新逻辑。
 * v2: 增加自动重试（3次指数退避）、超时处理（30s）、JSON 解析保护。
 */
import { ref, onUnmounted } from "vue";
import { useChatStore } from "@/stores/chat";

const MAX_RETRIES = 3;
const RETRY_BASE_DELAY_MS = 1000;
const READ_TIMEOUT_MS = 30_000;

export function useSSE() {
  const chat = useChatStore();
  const controller = ref<AbortController | null>(null);
  let retryCount = 0;

  async function send(query: string) {
    if (chat.isProcessing) return;

    retryCount = 0;
    chat.addUserMessage(query);
    chat.startStreaming();

    await connect(query);
  }

  async function connect(query: string) {
    const abort = new AbortController();
    controller.value = abort;

    let timeoutId: ReturnType<typeof setTimeout> | null = null;

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

      // 超时计时器：30s 无新数据则断开
      const resetTimeout = () => {
        if (timeoutId) clearTimeout(timeoutId);
        timeoutId = setTimeout(() => {
          chat.setError("连接超时：30秒未收到服务端响应");
          abort.abort();
        }, READ_TIMEOUT_MS);
      };
      resetTimeout();

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        resetTimeout();

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (line.startsWith("event: ")) {
            eventType = line.slice(7).trim();
          } else if (line.startsWith("data: ")) {
            const jsonStr = line.slice(6);
            if (!jsonStr.trim()) continue;
            try {
              const data = JSON.parse(jsonStr);
              handleEvent(eventType, data);
            } catch (parseErr) {
              console.warn("[SSE] JSON parse failed for event:", eventType, jsonStr.slice(0, 100), parseErr);
            }
          }
        }
      }

      if (timeoutId) clearTimeout(timeoutId);
    } catch (err: any) {
      if (timeoutId) clearTimeout(timeoutId);

      if (err.name === "AbortError") {
        return; // 用户主动取消，不重试
      }

      // 自动重试（指数退避）
      if (retryCount < MAX_RETRIES) {
        retryCount++;
        const delay = RETRY_BASE_DELAY_MS * Math.pow(2, retryCount - 1);
        console.warn(`[SSE] 连接断开，${delay}ms 后第 ${retryCount}/${MAX_RETRIES} 次重试...`);
        await new Promise((r) => setTimeout(r, delay));
        await connect(query);
      } else {
        chat.setError(err.message || "连接失败（已重试3次）");
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
      case "report":
        chat.addReport(data.content || data.final_report || "");
        break;
      case "done":
        chat.finishAnalysis(data.final_report || "", data.agents || null);
        break;
      case "token":
        chat.appendToken(data.token || "", data.agent || "llm");
        break;
      case "debate_score":
        chat.addDebateScore(data);
        break;
      case "eval":
        chat.addEval(data);
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
