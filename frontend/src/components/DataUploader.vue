<template>
  <div class="uploader">
    <div class="section-title">数据源</div>

    <label class="drop-zone" :class="{ dragging }">
      <input type="file" accept=".csv" @change="onFile" hidden ref="fileInput" />
      <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
      <span>拖拽或点击上传 CSV</span>
      <small>最大 50MB / 10万行</small>
    </label>

    <div v-if="uploading" class="upload-status">
      <div class="progress-bar"><div class="progress-fill" :style="{ width: uploadProgress + '%' }"></div></div>
      <small>{{ uploadStatus }}</small>
    </div>

    <div v-if="tables.length" class="table-list">
      <div class="section-title">已加载 ({{ tables.length }})</div>
      <div v-for="t in tableList" :key="t.name" class="table-item">
        <div class="table-name">{{ t.name }}</div>
        <div class="table-meta">{{ t.columns }} 列 &middot; {{ t.rows }} 行</div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from "vue";
import { uploadCSV, getTables } from "../api/index";
import { useChatStore } from "@/stores/chat";

const chat = useChatStore();
const fileInput = ref<HTMLInputElement>();
const uploading = ref(false);
const uploadProgress = ref(0);
const uploadStatus = ref("");
const dragging = ref(false);
const tableMap = ref<Record<string, any>>({});

const tables = computed(() => Object.keys(tableMap.value));
const tableList = computed(() =>
  Object.entries(tableMap.value).map(([name, info]) => ({
    name,
    columns: info.columns?.length || 0,
    rows: info.row_count || "?",
  }))
);

async function onFile(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0];
  if (!file) return;
  uploading.value = true; uploadProgress.value = 30; uploadStatus.value = `Uploading ${file.name}...`;
  try {
    const r = await uploadCSV(file);
    uploadProgress.value = 100; uploadStatus.value = `Done: ${r.table_name}`;
    tableMap.value[r.table_name] = r; chat.setTables(tables.value);
  } catch (err: any) { uploadStatus.value = `Failed: ${err.message}`; }
  setTimeout(() => (uploading.value = false), 2000);
}

async function load() { try { const r = await getTables(); tableMap.value = r; chat.setTables(tables.value); } catch {} }
load();
</script>

<style scoped>
.uploader { padding: 4px 0; }
.section-title { font-size: 10px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.8px; color: #64748b; margin-bottom: 8px; }
.drop-zone { display: flex; flex-direction: column; align-items: center; gap: 6px; padding: 24px 12px; border: 2px dashed #334155; border-radius: var(--radius); cursor: pointer; transition: all .15s; color: #94a3b8; }
.drop-zone:hover { border-color: var(--emerald); color: var(--emerald); background: rgba(5,150,105,.05); }
.drop-zone span { font-size: 13px; }
.drop-zone small { font-size: 10px; color: #64748b; }
.upload-status { margin-top: 8px; }
.progress-bar { height: 3px; background: #334155; border-radius: 2px; overflow: hidden; }
.progress-fill { height: 100%; background: var(--emerald); transition: width .3s; }
.upload-status small { font-size: 10px; color: #94a3b8; }
.table-list { margin-top: 20px; }
.table-item { padding: 8px 0; border-bottom: 1px solid #1e293b; }
.table-name { font-size: 13px; color: #e2e8f0; }
.table-meta { font-size: 10px; color: #64748b; margin-top: 2px; }
</style>
