<template>
  <div class="chart-card" v-if="chartJson">
    <div v-if="loading" class="chart-loading">
      <span class="loading-spinner"></span>
      <span>生成图表中...</span>
    </div>
    <div v-if="error" class="chart-error">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>
      <span>{{ error }}</span>
    </div>
    <div ref="container" class="chart-container" :class="{ hidden: loading || error }"></div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, onMounted, nextTick } from "vue";

const props = defineProps<{ chartJson: any }>();
const container = ref<HTMLElement>();
const loading = ref(false);
const error = ref("");

async function renderChart(json: any) {
  if (!json || !container.value) return;
  error.value = "";
  loading.value = true;
  await nextTick();
  try {
    const Plotly = await import("plotly.js-dist-min");
    const fig = typeof json === "string" ? JSON.parse(json) : json;

    if (!fig || !fig.data) {
      error.value = "图表数据格式无效";
      loading.value = false;
      return;
    }

    if (fig.layout) {
      fig.layout.template = "plotly_white";
      fig.layout.margin = { l: 48, r: 24, t: 36, b: 48 };
      fig.layout.font = {
        family: "-apple-system, 'Geist Sans', system-ui, sans-serif",
        size: 12,
        color: "#6B6B68",
      };
      fig.layout.title = {
        ...(fig.layout.title || {}),
        font: { size: 16, color: "#1A1A19", family: "-apple-system, 'Geist Sans', system-ui, sans-serif" },
      };
      fig.layout.xaxis = {
        ...(fig.layout.xaxis || {}),
        gridcolor: "#EBEBE8",
        zerolinecolor: "#EBEBE8",
      };
      fig.layout.yaxis = {
        ...(fig.layout.yaxis || {}),
        gridcolor: "#EBEBE8",
        zerolinecolor: "#EBEBE8",
      };
      fig.layout.paper_bgcolor = "transparent";
      fig.layout.plot_bgcolor = "transparent";
    }
    await Plotly.newPlot(container.value, fig.data, fig.layout, {
      responsive: true,
      displayModeBar: false,
    });
    loading.value = false;
  } catch (e) {
    console.error("Chart render error:", e);
    error.value = `图表渲染失败: ${e instanceof Error ? e.message : "未知错误"}`;
    loading.value = false;
  }
}

onMounted(() => { if (props.chartJson) renderChart(props.chartJson); });
watch(() => props.chartJson, (json) => { renderChart(json); });
</script>

<style scoped>
.chart-card {
  background: var(--stone-surface);
  border: 1px solid var(--stone-border);
  border-radius: var(--radius-lg);
  padding: 16px 20px 12px;
  min-height: 300px;
  position: relative;
}

.chart-container {
  width: 100%;
  min-height: 300px;
}

.chart-container.hidden {
  display: none;
}

.chart-loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  min-height: 300px;
  color: var(--ink-tertiary);
  font-size: 13px;
}

.loading-spinner {
  width: 24px;
  height: 24px;
  border: 2px solid var(--stone-border);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.chart-error {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-height: 300px;
  color: var(--amber);
  font-size: 13px;
}
</style>
