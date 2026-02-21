<template>
  <div class="app-shell">
    <aside class="sidebar">
      <div class="sidebar-brand">
        <div class="brand-icon">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
        </div>
        <div>
          <h1>DataForge</h1>
          <span>7 智能体 · LangGraph 编排</span>
        </div>
      </div>
      <DataUploader />
      <div class="sidebar-footer">
        <span class="status-dot" :class="{ live: storeReady }" />
        <span>{{ storeReady ? `${tables.length} 个数据表` : '等待上传数据' }}</span>
      </div>
    </aside>
    <main class="main">
      <router-view />
    </main>
  </div>
</template>

<script setup lang="ts">
import { useChatStore } from "@/stores/chat";
import DataUploader from "@/components/DataUploader.vue";
const chat = useChatStore();
const storeReady = chat.storeReady;
const tables = chat.tables;
</script>

<style>
:root {
  --slate-900: #0f172a; --slate-800: #1e293b; --slate-700: #334155;
  --slate-200: #e2e8f0; --slate-100: #f1f5f9; --slate-50: #f8fafc;
  --emerald: #059669; --emerald-light: #d1fae5; --emerald-bg: #ecfdf5;
  --amber: #d97706; --amber-light: #fef3c7; --amber-bg: #fffbeb;
  --red: #dc2626; --red-light: #fee2e2;
  --radius: 8px;
}
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif; background: var(--slate-50); color: #1e293b; -webkit-font-smoothing: antialiased; }
.app-shell { display: flex; height: 100vh; overflow: hidden; }
.sidebar { width: 280px; background: var(--slate-900); color: #e2e8f0; display: flex; flex-direction: column; flex-shrink: 0; }
.sidebar-brand { padding: 20px; border-bottom: 1px solid var(--slate-700); display: flex; align-items: center; gap: 12px; }
.brand-icon { color: var(--emerald); }
.sidebar-brand h1 { font-size: 16px; font-weight: 700; letter-spacing: -0.3px; }
.sidebar-brand span { font-size: 11px; color: #94a3b8; display: block; margin-top: 2px; }
.sidebar-footer { padding: 12px 20px; border-top: 1px solid var(--slate-700); font-size: 12px; color: #94a3b8; display: flex; align-items: center; gap: 8px; margin-top: auto; }
.status-dot { width: 7px; height: 7px; border-radius: 50%; background: #64748b; }
.status-dot.live { background: var(--emerald); }
.main { flex: 1; overflow: hidden; display: flex; flex-direction: column; background: #fff; }
</style>
