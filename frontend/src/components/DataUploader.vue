<template>
  <div class="uploader">
    <label class="drop-zone">
      <input type="file" accept=".csv" @change="onFile" hidden ref="fileInput" />
      <div class="drop-icon">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6">
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
          <polyline points="17 8 12 3 7 8"/>
          <line x1="12" y1="3" x2="12" y2="15"/>
        </svg>
      </div>
      <span class="drop-label">上传 CSV</span>
    </label>

    <div v-if="uploading" class="upload-status">
      <div class="progress-bar"><div class="progress-fill" :style="{ width: uploadProgress + '%' }"></div></div>
      <span class="status-msg">{{ uploadStatus }}</span>
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
const tableMap = ref<Record<string, any>>({});

const tables = computed(() => Object.keys(tableMap.value));

async function onFile(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0];
  if (!file) return;
  uploading.value = true; uploadProgress.value = 30; uploadStatus.value = `正在上传 ${file.name}...`;
  try {
    const r = await uploadCSV(file);
    uploadProgress.value = 100; uploadStatus.value = `已导入: ${r.table_name}`;
    tableMap.value[r.table_name] = r;
    chat.setTables(tables.value);
  } catch (err: any) {
    uploadStatus.value = `上传失败: ${err.message}`;
  }
  setTimeout(() => (uploading.value = false), 2000);
}

async function load() {
  try {
    const r = await getTables();
    tableMap.value = r;
    chat.setTables(tables.value);
  } catch {}
}
load();
</script>

<style scoped>
.uploader {
  padding: 4px 0;
}

.drop-zone {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 12px;
  border: 1px dashed var(--sidebar-border);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: all var(--duration-fast) var(--ease-out-expo);
  color: var(--sidebar-text);
}

.drop-zone:hover {
  border-color: var(--accent);
  color: var(--accent);
  background: rgba(5, 150, 105, 0.06);
}

.drop-icon {
  flex-shrink: 0;
  display: flex;
  align-items: center;
}

.drop-label {
  font-size: 12.5px;
  font-weight: 480;
}

.upload-status {
  margin-top: 8px;
  padding: 0 4px;
}

.progress-bar {
  height: 3px;
  background: var(--sidebar-surface);
  border-radius: 99px;
  overflow: hidden;
  margin-bottom: 4px;
}

.progress-fill {
  height: 100%;
  background: var(--accent);
  border-radius: 99px;
  transition: width 0.4s var(--ease-out-expo);
}

.status-msg {
  font-size: 10.5px;
  color: var(--sidebar-text);
}
</style>
