import { describe, it, expect, beforeEach } from "vitest";
import { setActivePinia, createPinia } from "pinia";
import { useChatStore } from "@/stores/chat";

describe("ChatStore", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("adds user messages", () => {
    const store = useChatStore();
    store.addUserMessage("Hello");
    expect(store.messages).toHaveLength(1);
    expect(store.messages[0].role).toBe("user");
    expect(store.messages[0].content).toBe("Hello");
  });

  it("tracks streaming state", () => {
    const store = useChatStore();
    expect(store.isProcessing).toBe(false);
    store.startStreaming();
    expect(store.isProcessing).toBe(true);
  });

  it("adds step messages", () => {
    const store = useChatStore();
    store.addStep("SQL Agent", "Executing query...");
    expect(store.messages).toHaveLength(1);
    expect(store.messages[0].type).toBe("step");
    expect(store.messages[0].agent).toBe("SQL Agent");
  });

  it("appends streaming tokens", () => {
    const store = useChatStore();
    store.appendToken("SELECT", "llm");
    store.appendToken(" * FROM", "llm");
    expect(store.streamingTokens["llm"]).toBe("SELECT * FROM");
    expect(store.currentStreamingAgent).toBe("llm");
  });

  it("clears messages and streaming state", () => {
    const store = useChatStore();
    store.addUserMessage("test");
    store.appendToken("hello", "llm");
    store.clearMessages();
    expect(store.messages).toHaveLength(0);
    expect(store.streamingTokens).toEqual({});
    expect(store.currentStreamingAgent).toBeNull();
  });

  it("adds debate score messages", () => {
    const store = useChatStore();
    store.addDebateScore({
      optimistic_score: 85,
      pessimistic_score: 72,
      winner_label: "Optimistic View wins",
    });
    expect(store.messages).toHaveLength(1);
    const msg = store.messages[0];
    expect(msg.type).toBe("debate_score");
    expect(msg.optScore).toBe(85);
    expect(msg.pessScore).toBe(72);
  });

  it("handles finish analysis lifecycle", () => {
    const store = useChatStore();
    store.startStreaming();
    expect(store.isProcessing).toBe(true);
    store.finishAnalysis("Final report content", { planner: { plan: [] } });
    expect(store.isProcessing).toBe(false);
    expect(store.currentStage).toBe("完成");
    expect(store.streamingTokens).toEqual({});
  });

  it("sets and tracks tables", () => {
    const store = useChatStore();
    expect(store.storeReady).toBe(false);
    store.setTables(["sales", "reviews"]);
    expect(store.tables).toEqual(["sales", "reviews"]);
    expect(store.storeReady).toBe(true);
  });

  // ─── 新增：SSE 事件路由测试 ───

  it("routes 'step' events to addStep with agent labels", () => {
    const store = useChatStore();
    // Simulate SSE step event handling
    store.addStep("SQL Agent", "正在查询数据...");
    const msg = store.messages[0];
    expect(msg.type).toBe("step");
    expect(msg.agent).toBe("SQL Agent");
    expect(msg.agentLabel).toBeTruthy();
    expect(msg.content).toBe("正在查询数据...");
  });

  it("routes 'chart' events to addChart", () => {
    const store = useChatStore();
    const chartData = { data: [{ type: "bar", x: [1, 2], y: [3, 4] }] };
    store.addChart(chartData);
    expect(store.messages).toHaveLength(1);
    expect(store.messages[0].type).toBe("chart");
    expect(store.messages[0].chartJson).toEqual(chartData);
  });

  it("routes 'debate' events to addDebate", () => {
    const store = useChatStore();
    store.addDebate("Optimistic", "数据显示该品牌表现优异");
    expect(store.messages).toHaveLength(1);
    expect(store.messages[0].type).toBe("debate");
    expect(store.messages[0].agent).toBe("Optimistic");
  });

  it("routes 'eval' events and stores _eval data", () => {
    const store = useChatStore();
    const evalData = { overall_score: 0.85, passed: true, warnings: [] };
    store.addEval(evalData);
    expect(store.messages).toHaveLength(1);
    expect(store.messages[0].type).toBe("eval");
    expect(store.messages[0]._eval).toEqual(evalData);
  });

  it("routes 'error' events to setError", () => {
    const store = useChatStore();
    store.setError("API Key 无效");
    expect(store.error).toBe("API Key 无效");
    expect(store.isProcessing).toBe(false);
  });

  it("handles token streaming with multiple agents", () => {
    const store = useChatStore();
    store.appendToken("分析中", "Planner");
    store.appendToken("...", "Planner");
    store.appendToken("SELECT", "SQL Agent");
    expect(store.streamingTokens["Planner"]).toBe("分析中...");
    expect(store.streamingTokens["SQL Agent"]).toBe("SELECT");
    expect(store.currentStreamingAgent).toBe("SQL Agent");
  });

  it("clearMessages resets all state", () => {
    const store = useChatStore();
    store.addUserMessage("query");
    store.addStep("Planner", "planning");
    store.setError("some error");
    store.addEval({ overall_score: 0.5, passed: true, warnings: ["w1"] });

    store.clearMessages();

    expect(store.messages).toHaveLength(0);
    expect(store.error).toBe("");
    expect(store.currentStage).toBe("就绪");
    expect(store.agentResults).toBeNull();
    expect(store.streamingTokens).toEqual({});
    expect(store.currentStreamingAgent).toBeNull();
  });

  it("debate score message format is complete", () => {
    const store = useChatStore();
    store.addDebateScore({
      optimistic_score: 78,
      pessimistic_score: 65,
      winner_label: "Optimistic wins by argument quality",
    });

    const msg = store.messages[0];
    expect(msg.optScore).toBe(78);
    expect(msg.pessScore).toBe(65);
    expect(msg.winnerLabel).toContain("Optimistic");
    expect(msg.type).toBe("debate_score");
  });

  it("addStep uses Chinese labels from AGENT_LABELS map", () => {
    const store = useChatStore();

    const expectedLabels: Record<string, string> = {
      "Planner": "任务规划",
      "SQL Agent": "数据查询",
      "Chart Agent": "生成图表",
      "Report Agent": "撰写报告",
      "Optimistic": "乐观方辩论",
      "Pessimistic": "谨慎方辩论",
      "Validator": "裁判验证",
    };

    for (const [agent, label] of Object.entries(expectedLabels)) {
      store.clearMessages();
      store.addStep(agent, "working...");
      expect(store.messages[0].agentLabel).toBe(label);
    }
  });
});
