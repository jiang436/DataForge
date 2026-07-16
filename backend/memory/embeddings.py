"""
多 Provider Embedding 工厂

参考: tradingagents/agents/utils/memory.py → get_embedding()

支持多种 Embedding 来源，优先阿里云 DashScope:
  1. 阿里云 DashScope text-embedding-v3（推荐，中文最优）
  2. OpenAI 兼容 API（DeepSeek/OpenAI/GLM 通用）
  3. 本地 sentence-transformers（离线可用）
  4. 哈希回退（永不崩溃）
"""

import logging
import os
import threading
from collections.abc import Callable

logger = logging.getLogger("memory")


class EmbeddingProvider:
    """
    Embedding 提供器 — 多源自动降级

    优先级: 阿里云 DashScope → OpenAI 兼容 → 本地模型 → 哈希回退
    """

    def __init__(self, llm_provider: str = "deepseek"):
        self.llm_provider = llm_provider
        self._embed_fn: Callable | None = None
        self._init_lock = threading.Lock()
        self._source = "uninitialized"
        self._dimension = 1024  # DashScope text-embedding-v3 默认维度

    def embed(self, texts: list[str]) -> list[list[float]]:
        """对文本列表做向量化"""
        if self._embed_fn is None:
            with self._init_lock:
                if self._embed_fn is None:
                    self._embed_fn = self._resolve_embedding_fn()
        try:
            return self._embed_fn(texts)
        except Exception as e:
            logger.warning("Embedding 失败，降级到零向量: %s", e)
            return [[0.0] * self._dimension for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        return self.embed([text])[0]

    @property
    def source(self) -> str:
        return self._source

    @property
    def dimension(self) -> int:
        return self._dimension

    # ═══════════════════════════════════════════════
    def _resolve_embedding_fn(self) -> Callable:
        # 1️⃣ 阿里云 DashScope（推荐，中文最优）
        fn = self._try_dashscope()
        if fn:
            self._source = "aliyun (dashscope text-embedding-v3)"
            logger.info("Embedding: 阿里云 DashScope, 维度=%d", self._dimension)
            return fn

        # 2️⃣ OpenAI 兼容 API
        fn = self._try_openai_compatible()
        if fn:
            self._source = f"openai-compatible ({self.llm_provider})"
            logger.info("Embedding: OpenAI 兼容 (%s), 维度=%d", self.llm_provider, self._dimension)
            return fn

        # 3️⃣ 本地 sentence-transformers
        fn = self._try_local()
        if fn:
            self._source = "local (all-MiniLM-L6-v2)"
            logger.info("Embedding: 本地模型, 维度=%d", self._dimension)
            return fn

        # 4️⃣ 哈希回退
        self._source = "fallback (hash)"
        self._dimension = 384
        logger.warning("Embedding: 全部不可用，回退到哈希（语义精度降低）")
        return self._hash_embedding

    def _try_dashscope(self) -> Callable | None:
        """阿里云 DashScope text-embedding-v3"""
        api_key = os.getenv("DASHSCOPE_API_KEY", "")
        if not api_key:
            return None
        try:
            import dashscope
            from dashscope import TextEmbedding

            dashscope.api_key = api_key
            self._dimension = 1024

            def _embed(texts: list[str]) -> list[list[float]]:
                result = []
                for text in texts:
                    resp = TextEmbedding.call(model="text-embedding-v3", input=text)
                    if resp.status_code == 200:
                        result.append(resp.output["embeddings"][0]["embedding"])
                    else:
                        logger.warning("DashScope embedding 失败: %s - %s", resp.code, resp.message)
                        result.append([0.0] * self._dimension)
                return result

            # 验证可用性
            TextEmbedding.call(model="text-embedding-v3", input="test")
            return _embed
        except ImportError:
            logger.debug("dashscope 包未安装")
            return None
        except Exception as e:
            logger.debug("DashScope 不可用: %s", e)
            return None

    def _try_openai_compatible(self) -> Callable | None:
        """OpenAI 兼容 embedding API"""
        try:
            from openai import OpenAI

            configs = {
                "deepseek": ("https://api.deepseek.com", "DEEPSEEK_API_KEY"),
                "openai": ("https://api.openai.com/v1", "OPENAI_API_KEY"),
                "qwen": ("https://dashscope.aliyuncs.com/compatible-mode/v1", "DASHSCOPE_API_KEY"),
                "glm": ("https://open.bigmodel.cn/api/paas/v4", "ZHIPU_API_KEY"),
            }
            cfg = configs.get(self.llm_provider)
            if not cfg:
                return None

            base_url, env_key = cfg
            api_key = os.getenv(env_key, "")
            if not api_key:
                return None

            client = OpenAI(api_key=api_key, base_url=base_url)
            resp = client.embeddings.create(model="text-embedding-3-small", input=["test"])
            self._dimension = len(resp.data[0].embedding)

            def _embed(texts: list[str]) -> list[list[float]]:
                r = client.embeddings.create(model="text-embedding-3-small", input=texts)
                return [d.embedding for d in r.data]

            return _embed
        except Exception as e:
            logger.debug("OpenAI 兼容 embedding 不可用: %s", e)
            return None

    def _try_local(self) -> Callable | None:
        """本地 sentence-transformers"""
        try:
            from sentence_transformers import SentenceTransformer

            model = SentenceTransformer("all-MiniLM-L6-v2")
            self._dimension = model.get_sentence_embedding_dimension()

            def _embed(texts):
                return model.encode(texts, normalize_embeddings=True).tolist()

            return _embed
        except ImportError:
            logger.debug("sentence-transformers 未安装")
            return None
        except Exception as e:
            logger.debug("本地模型加载失败: %s", e)
            return None

    @staticmethod
    def _hash_embedding(texts: list[str]) -> list[list[float]]:
        import hashlib

        dim, result = 384, []
        for text in texts:
            vec, seed = [], text.encode("utf-8")
            while len(vec) < dim:
                seed = hashlib.sha256(seed).digest()
                for i in range(0, len(seed), 4):
                    if len(vec) >= dim:
                        break
                    chunk = seed[i : i + 4]
                    if len(chunk) < 4:
                        break
                    vec.append(int.from_bytes(chunk, "big") / (2**31) - 1.0)
            result.append(vec)
        return result
