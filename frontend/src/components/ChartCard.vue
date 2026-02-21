<template>
  <div class="chart-card" v-if="chartJson">
    <div ref="container" class="chart-container"></div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, onMounted, nextTick } from "vue";
const props = defineProps<{ chartJson: any }>();
const container = ref<HTMLElement>();

async function renderChart(json: any) {
  if (!json || !container.value) return;
  await nextTick();
  try {
    const Plotly = await import("plotly.js-dist-min");
    const fig = typeof json === "string" ? JSON.parse(json) : json;
    if (fig.layout) {
      fig.layout.template = "plotly_white";
      fig.layout.margin = { l: 40, r: 20, t: 30, b: 40 };
      fig.layout.font = { family: "-apple-system, sans-serif", size: 11 };
    }
    Plotly.newPlot(container.value, fig.data, fig.layout, { responsive: true, displayModeBar: false });
  } catch (e) { console.error(e); }
}

onMounted(() => { if (props.chartJson) renderChart(props.chartJson); });
watch(() => props.chartJson, (json) => { renderChart(json); });
</script>

<style scoped>
.chart-card { background: #fff; border: 1px solid #e5e7eb; border-radius: var(--radius); padding: 8px; }
.chart-container { width: 100%; min-height: 280px; }
</style>
