"""
自适应缓存管理器

参考: tradingagents/dataflows/cache/adaptive.py

三层回退策略:
  1. 内存 LRU 缓存（最快）
  2. 文件缓存（持久化）
  3. 回退到原始数据源（总是可用）

用法:
    cache = AdaptiveCache(max_memory_entries=100, ttl_seconds=3600)
    cached = cache.get("key", lambda: fetch_from_source())
"""

import hashlib
import json
import logging
import time
from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path
from typing import Any

logger = logging.getLogger("cache")


class _LRUCache:
    """线程不安全的简单 LRU 缓存"""

    def __init__(self, max_size: int = 100):
        self.max_size = max_size
        self._store: OrderedDict[str, tuple[float, Any]] = OrderedDict()

    def get(self, key: str, ttl: float) -> Any | None:
        if key not in self._store:
            return None
        expiry, value = self._store[key]
        if time.time() > expiry:
            del self._store[key]
            return None
        self._store.move_to_end(key)
        return value

    def set(self, key: str, value: Any, ttl: float):
        if key in self._store:
            self._store.move_to_end(key)
        self._store[key] = (time.time() + ttl, value)
        while len(self._store) > self.max_size:
            self._store.popitem(last=False)


class AdaptiveCache:
    """
    自适应三层缓存

    面试话术: "我实现了一个自适应缓存层，优先用内存 LRU，持久化层用文件，
    任何一层失败自动降级到下一层，保证系统在任何情况下都能正常工作。"
    """

    def __init__(
        self,
        max_memory_entries: int = 100,
        ttl_seconds: int = 3600,
        file_cache_dir: str = "data/cache",
    ):
        self.ttl = ttl_seconds
        self._memory = _LRUCache(max_size=max_memory_entries)
        self._file_dir = Path(file_cache_dir)
        self._file_dir.mkdir(parents=True, exist_ok=True)
        logger.info(
            "缓存就绪: 内存=%d 条, TTL=%ds, 文件目录=%s",
            max_memory_entries,
            ttl_seconds,
            self._file_dir,
        )

    def get(self, key: str, fallback: Callable[[], Any] | None = None) -> Any | None:
        """
        从缓存获取，未命中时调用 fallback 并自动存入缓存

        Args:
            key:      缓存键
            fallback: 未命中时的数据源回调

        Returns:
            缓存值，或 fallback 结果
        """
        cache_key = self._hash(key)

        # 1. 内存缓存
        try:
            value = self._memory.get(cache_key, self.ttl)
            if value is not None:
                logger.debug("缓存命中: 内存 ← %s", key[:50])
                return value
        except Exception as e:
            logger.debug("内存缓存异常: %s", e)

        # 2. 文件缓存
        try:
            value = self._file_get(cache_key)
            if value is not None:
                self._memory.set(cache_key, value, self.ttl)
                logger.debug("缓存命中: 文件 ← %s", key[:50])
                return value
        except Exception as e:
            logger.debug("文件缓存异常: %s", e)

        # 3. 回退到原始数据源
        if fallback is not None:
            try:
                value = fallback()
                if value is not None:
                    self._memory.set(cache_key, value, self.ttl)
                    self._file_set(cache_key, value)
                    logger.debug("缓存写入: %s", key[:50])
                return value
            except Exception as e:
                logger.warning("数据源回退失败: %s", e)

        return None

    def invalidate(self, key: str):
        """清除指定缓存"""
        cache_key = self._hash(key)
        try:
            if cache_key in self._memory._store:
                del self._memory._store[cache_key]
        except Exception:
            pass
        filepath = self._file_dir / f"{cache_key}.json"
        if filepath.exists():
            filepath.unlink()

    def clear(self):
        """清空所有缓存"""
        self._memory._store.clear()
        for f in self._file_dir.glob("*.json"):
            f.unlink()
        logger.info("缓存已清空")

    # ─── 私有方法 ───

    @staticmethod
    def _hash(key: str) -> str:
        return hashlib.md5(key.encode()).hexdigest()[:16]

    def _file_get(self, cache_key: str) -> Any | None:
        filepath = self._file_dir / f"{cache_key}.json"
        if not filepath.exists():
            return None
        try:
            data = json.loads(filepath.read_text(encoding="utf-8"))
            if time.time() > data.get("expiry", 0):
                filepath.unlink()
                return None
            return data.get("value")
        except Exception:
            return None

    def _file_set(self, cache_key: str, value: Any):
        filepath = self._file_dir / f"{cache_key}.json"
        try:
            filepath.write_text(
                json.dumps(
                    {
                        "expiry": time.time() + self.ttl,
                        "value": value,
                    },
                    ensure_ascii=False,
                    default=str,
                ),
                encoding="utf-8",
            )
        except Exception as e:
            logger.debug("文件缓存写入失败: %s", e)
