<template>
  <div class="app-shell">
    <!-- Sidebar: dark, premium, restrained -->
    <aside class="sidebar">
      <div class="sidebar-brand">
        <div class="brand-mark">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
            <rect x="3" y="3" width="7" height="7" rx="1.5" stroke="currentColor" stroke-width="1.8"/>
            <rect x="14" y="3" width="7" height="7" rx="1.5" stroke="currentColor" stroke-width="1.8"/>
            <rect x="3" y="14" width="7" height="7" rx="1.5" stroke="currentColor" stroke-width="1.8"/>
            <rect x="14" y="14" width="7" height="7" rx="1.5" stroke="currentColor" stroke-width="1.8"/>
          </svg>
        </div>
        <div class="brand-text">
          <span class="brand-name">DataForge</span>
          <span class="brand-sub">多智能体数据分析</span>
        </div>
      </div>

      <nav class="sidebar-nav">
        <div class="nav-section-label">工作区</div>
        <a class="nav-item active" @click.prevent>
          <span class="nav-icon">
            <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>
          </span>
          <span>分析</span>
        </a>
      </nav>

      <div class="sidebar-section">
        <div class="nav-section-label">数据表</div>
        <DataUploader />
        <div class="tables-list" v-if="chat.tables.length">
          <div v-for="t in chat.tables" :key="t" class="table-chip">
            <svg width="8" height="8" viewBox="0 0 8 8" fill="currentColor"><circle cx="4" cy="4" r="3"/></svg>
            <span>{{ t }}</span>
          </div>
        </div>
        <div v-else class="nav-empty">上传 CSV 开始分析</div>
      </div>

      <div class="sidebar-footer">
        <div class="status-row">
          <span class="status-dot" :class="{ active: chat.isProcessing }"></span>
          <span class="status-text">{{ chat.isProcessing ? chat.currentStage : '就绪' }}</span>
        </div>
        <div class="footer-meta">
          <span>7 Agents</span>
          <span>LangGraph</span>
          <span v-if="chat.tables.length">{{ chat.tables.length }} 张表</span>
        </div>
      </div>
    </aside>

    <!-- Main content -->
    <main class="main-area">
      <router-view />
    </main>
  </div>
</template>

<script setup lang="ts">
import { useChatStore } from "@/stores/chat";
import DataUploader from "@/components/DataUploader.vue";

const chat = useChatStore();
</script>

<style>
@import "@/styles/tokens.css";

*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

body {
  font-family: var(--font-sans);
  background: var(--stone-bg);
  color: var(--ink-primary);
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  font-size: 14px;
  line-height: 1.5;
}

::-webkit-scrollbar { width: 5px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--ink-tertiary); border-radius: 99px; }
::-webkit-scrollbar-thumb:hover { background: var(--ink-secondary); }
</style>

<style scoped>
.app-shell {
  display: flex;
  height: 100vh;
  overflow: hidden;
}

/* ─── Sidebar ─── */
.sidebar {
  width: var(--sidebar-width);
  min-width: var(--sidebar-width);
  background: var(--sidebar-bg);
  display: flex;
  flex-direction: column;
  border-right: 1px solid var(--sidebar-border);
  user-select: none;
}

.sidebar-brand {
  padding: 22px 18px 18px;
  display: flex;
  align-items: center;
  gap: 11px;
  border-bottom: 1px solid var(--sidebar-border);
}

.brand-mark {
  width: 34px;
  height: 34px;
  background: var(--sidebar-surface);
  border: 1px solid var(--sidebar-border);
  border-radius: var(--radius-md);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--accent);
  flex-shrink: 0;
}

.brand-text {
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.brand-name {
  font-size: 15px;
  font-weight: 650;
  color: var(--sidebar-active);
  letter-spacing: -0.01em;
  line-height: 1.2;
}

.brand-sub {
  font-size: 10.5px;
  color: var(--sidebar-text);
  letter-spacing: 0.02em;
}

/* ─── Nav ─── */
.sidebar-nav {
  padding: 14px 12px 8px;
}

.nav-section-label {
  font-size: 10px;
  font-weight: 600;
  color: var(--sidebar-text);
  text-transform: uppercase;
  letter-spacing: 0.09em;
  padding: 8px 8px 6px;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 10px;
  border-radius: var(--radius-md);
  color: var(--sidebar-text);
  font-size: 13.5px;
  font-weight: 480;
  text-decoration: none;
  cursor: pointer;
  transition: all var(--duration-fast) var(--ease-out-expo);
}

.nav-item:hover {
  background: var(--sidebar-surface);
  color: var(--sidebar-active);
}

.nav-item.active {
  background: var(--sidebar-surface);
  color: var(--accent);
  font-weight: 550;
}

.nav-icon {
  flex-shrink: 0;
  display: flex;
  align-items: center;
}

/* ─── Tables ─── */
.sidebar-section {
  flex: 1;
  padding: 0 12px;
  overflow-y: auto;
}

.tables-list {
  display: flex;
  flex-direction: column;
  gap: 1px;
  padding: 2px 4px;
}

.table-chip {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 5px 10px;
  border-radius: var(--radius-sm);
  font-size: 12px;
  color: var(--sidebar-text);
  font-family: var(--font-mono);
}

.table-chip svg {
  color: var(--accent);
  flex-shrink: 0;
}

.nav-empty {
  font-size: 11.5px;
  color: var(--sidebar-text);
  padding: 6px 12px;
  opacity: 0.5;
}

/* ─── Footer ─── */
.sidebar-footer {
  padding: 12px 16px;
  border-top: 1px solid var(--sidebar-border);
}

.status-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.status-text {
  font-size: 12px;
  color: var(--sidebar-text);
}

.status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--ink-tertiary);
  flex-shrink: 0;
}

.status-dot.active {
  background: var(--accent);
  animation: pulse-dot 2s ease-in-out infinite;
}

@keyframes pulse-dot {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}

.footer-meta {
  display: flex;
  gap: 14px;
  margin-top: 8px;
  font-size: 10px;
  color: var(--sidebar-text);
  opacity: 0.45;
  letter-spacing: 0.04em;
}

/* ─── Main ─── */
.main-area {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  overflow: hidden;
  background: var(--stone-bg);
}
</style>
