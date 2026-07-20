"""
ChromaDB 向量记忆库 — 仿 TradingAgents-CN 的 Per-Agent 记忆架构


核心变更（v3.0 — Per-Agent RAG）:
  原: 单一 AnalysisMemory，全局共享 "analysis_history" collection
  新: 每个 Agent 拥有独立的 ChromaDB collection（参考 TradingAgents-CN 的
      bull_memory / bear_memory / trader_memory 模式）

架构:
  AgentMemory("planner")       → collection: "agent_planner"
  AgentMemory("sql_agent")     → collection: "agent_sql_agent"
  AgentMemory("chart_agent")   → collection: "agent_chart_agent"
  AgentMemory("report_agent")  → collection: "agent_report_agent"
  AgentMemory("optimistic")    → collection: "agent_optimistic"
  AgentMemory("pessimistic")   → collection: "agent_pessimistic"
  AgentMemory("validator")     → collection: "agent_validator"

每个 Agent 独立存储和检索自己领域的经验，互不干扰。
"""

import hashlib
import logging
import os
import threading

import chromadb
from chromadb.config import Settings

from backend.memory.embeddings import EmbeddingProvider
from backend.utils.text_chunker import smart_truncate

logger = logging.getLogger("memory")


class ChromaDBManager:
    """ChromaDB 单例管理器 — 所有 AgentMemory 共享同一个 client"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._embed_provider = EmbeddingProvider(
            llm_provider=os.getenv("LLM_PROVIDER", "deepseek")
        )

        try:
            persist_dir = os.getenv("CHROMA_PERSIST_DIR", "data/chroma_db")
            os.makedirs(persist_dir, exist_ok=True)

            self._client = chromadb.Client(Settings(
                anonymized_telemetry=False,
                is_persistent=True,
                persist_directory=persist_dir,
            ))
            self._mode = "persistent"
            logger.info(
                "ChromaDB 就绪: 持久化=%s, Embedding=%s (维度=%d)",
                persist_dir, self._embed_provider.source, self._embed_provider.dimension,
            )
        except Exception as e:
            logger.warning("ChromaDB 持久化失败，使用内存模式: %s", e)
            try:
                self._client = chromadb.Client(
                    Settings(anonymized_telemetry=False, is_persistent=False)
                )
                self._mode = "memory"
            except Exception as e2:
                logger.error("ChromaDB 完全不可用: %s", e2)
                self._client = None
                self._mode = "unavailable"

        self._initialized = True

    def get_or_create(self, name: str):
        """获取或创建 collection"""
        if self._client is None:
            return None
        with self._lock:
            try:
                return self._client.get_collection(name=name)
            except Exception:
                try:
                    return self._client.create_collection(name=name)
                except Exception:
                    try:
                        self._client.delete_collection(name=name)
                        return self._client.create_collection(name=name)
                    except Exception:
                        return self._client.get_collection(name=name)

    @property
    def embed_source(self) -> str:
        return self._embed_provider.source

    @property
    def embed_dimension(self) -> int:
        return self._embed_provider.dimension

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def embed_provider(self):
        return self._embed_provider

    @property
    def client(self):
        return self._client


# ═══════════════════════════════════════════════════════════
# Per-Agent 记忆库 — 仿 FinancialSituationMemory
# ═══════════════════════════════════════════════════════════


class AgentMemory:
    """
    单个 Agent 的专属向量记忆库

    每个 Agent 拥有独立的 ChromaDB collection，存储和检索自己领域的经验。

    用法:
        sql_memory = AgentMemory("sql_agent")
        sql_memory.add_experience(
            situation="用户问所有产品的销售额排名",
            advice="使用 SELECT product, SUM(amount) GROUP BY product",
            outcome="查询成功，返回5个品牌"
        )
        similar = sql_memory.query("按品牌汇总销售额", n=2)
    """

    def __init__(self, agent_name: str):
        self.agent_name = agent_name
        self.collection_name = f"agent_{agent_name}"
        self._chroma = None
        self._collection = None

    @property
    def chroma(self):
        if self._chroma is None:
            self._chroma = ChromaDBManager()
        return self._chroma

    @property
    def collection(self):
        if self._collection is None:
            self._collection = self.chroma.get_or_create(self.collection_name)
        return self._collection

    def add_experience(
        self,
        situation: str,
        advice: str = "",
        outcome: str = "",
    ) -> str:
        """
        存储一次经验

        Args:
            situation: 当前场景描述（用于向量检索）
            advice:    对应的决策/建议
            outcome:   执行结果
        """
        memory_id = hashlib.md5(
            f"{self.agent_name}_{situation[:100]}_{len(advice)}".encode()
        ).hexdigest()[:16]

        if self.collection is None:
            logger.debug("[%s] ChromaDB 不可用，跳过存储", self.agent_name)
            return memory_id

        document = smart_truncate(f"场景: {situation}\n决策: {advice}", max_length=2000)

        try:
            # 先生成 embedding（手动指定，而非依赖 ChromaDB 内置函数）
            embedding = self.chroma.embed_provider.embed([document])[0]

            self.collection.add(
                documents=[document],
                metadatas=[{
                    "situation": situation[:500],
                    "advice": advice[:500],
                    "outcome": outcome[:300],
                }],
                embeddings=[embedding],
                ids=[memory_id],
            )
            logger.debug("[%s] 经验已存储: %s", self.agent_name, memory_id)
        except Exception as e:
            logger.warning("[%s] 存储经验失败（非致命）: %s", self.agent_name, e)

        return memory_id

    def query(self, current_situation: str, n: int = 2) -> list[dict]:
        """
        检索与当前场景最相似的历史经验

        Args:
            current_situation: 当前场景文本
            n: 返回条数

        Returns:
            [{"situation": "...", "advice": "...", "outcome": "...", "score": 0.95}, ...]
        """
        if self.collection is None:
            return []

        try:
            count = self.collection.count()
        except Exception:
            return []

        if count == 0:
            return []

        n = min(n, count)

        try:
            query_embedding = self.chroma.embed_provider.embed([current_situation[:1000]])[0]

            results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=n,
            )

            memories = []
            if results and results.get("metadatas"):
                metadatas = results["metadatas"][0]
                distances = results.get("distances", [[]])[0]

                for i, meta in enumerate(metadatas):
                    memories.append({
                        "situation": meta.get("situation", ""),
                        "advice": meta.get("advice", ""),
                        "outcome": meta.get("outcome", ""),
                        "score": round(1.0 - distances[i], 4) if i < len(distances) else 0,
                    })

            if memories:
                logger.info(
                    "[%s] 检索到 %d 条相关经验 (最高分: %.2f)",
                    self.agent_name, len(memories),
                    max(m.get("score", 0) for m in memories),
                )
            return memories
        except Exception as e:
            logger.warning("[%s] 记忆检索失败（非致命）: %s", self.agent_name, e)
            return []

    def clear(self):
        """清空此 Agent 的记忆"""
        try:
            if self.chroma.client:
                self.chroma.client.delete_collection(self.collection_name)
            self._collection = self.chroma.get_or_create(self.collection_name)
            logger.info("[%s] 记忆已清空", self.agent_name)
        except Exception as e:
            logger.warning("[%s] 清空失败: %s", self.agent_name, e)

    @property
    def count(self) -> int:
        if self.collection is None:
            return 0
        try:
            return self.collection.count()
        except Exception:
            return 0

    @property
    def info(self) -> dict:
        return {
            "agent": self.agent_name,
            "collection": self.collection_name,
            "count": self.count,
            "embed_source": self.chroma.embed_source,
        }

    def format_context(self, current_situation: str, n: int = 2) -> str:
        """
        检索历史经验并格式化为可直接注入 Agent prompt 的文本

        输出格式（仿 TradingAgents-CN）:
            ## 📚 历史经验 (Agent: sql_agent)
            ### 相关场景 1 (相似度: 0.92)
            场景: ...
            建议: ...

        Returns:
            格式化的上下文文本，无历史时返回空字符串
        """
        memories = self.query(current_situation, n=n)
        if not memories:
            return ""

        lines = [f"\n## 📚 历史经验 ({self.agent_name})\n"]
        for i, m in enumerate(memories, 1):
            lines.append(f"### 相关场景 {i} (相似度: {m['score']:.2f})")
            lines.append(f"**场景**: {m['situation']}")
            if m["advice"]:
                lines.append(f"**建议**: {m['advice']}")
            if m["outcome"]:
                lines.append(f"**结果**: {m['outcome']}")
            lines.append("")

        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════
# 全局 Agent 记忆库工厂
# ═══════════════════════════════════════════════════════════


# 所有 Agent 的记忆库名称（仿 TradingAgents-CN 的 5 个独立 memory）
AGENT_MEMORY_NAMES = [
    "planner",
    "sql_agent",
    "chart_agent",
    "report_agent",
    "optimistic",
    "pessimistic",
    "validator",
]

# 全局缓存
_agent_memories: dict[str, AgentMemory] = {}
_lock = threading.Lock()


def get_agent_memory(agent_name: str) -> AgentMemory:
    """获取指定 Agent 的记忆库实例（线程安全）"""
    with _lock:
        if agent_name not in _agent_memories:
            _agent_memories[agent_name] = AgentMemory(agent_name)
        return _agent_memories[agent_name]


def get_all_agent_memories() -> dict[str, AgentMemory]:
    """获取所有 7 个 Agent 的记忆库实例"""
    return {name: get_agent_memory(name) for name in AGENT_MEMORY_NAMES}


def reset_all_memories():
    """重置所有记忆库（测试隔离用）"""
    global _agent_memories
    with _lock:
        _agent_memories.clear()


# ─── 兼容旧接口 ───


def get_memory() -> AgentMemory:
    """兼容旧接口 — 返回 planner 的记忆库作为全局入口"""
    return get_agent_memory("planner")
