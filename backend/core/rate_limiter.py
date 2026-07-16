"""
滑动窗口速率限制器

参考: app/core/rate_limiter.py

轻量级实现，不依赖 Redis —— 仅内存模式，适合单机演示。
"""

import logging
import time
from collections import deque

logger = logging.getLogger("api")


class RateLimiter:
    """
    滑动窗口速率限制器

    用法:
        limiter = RateLimiter(max_calls=30, window=60)  # 每分钟 30 次
        if limiter.acquire("127.0.0.1"):
            process()
        else:
            raise HTTPException(429)
    """

    def __init__(self, max_calls: int = 30, window_seconds: float = 60.0):
        self.max_calls = max_calls
        self.window = window_seconds
        self._clients: dict[str, deque[float]] = {}

    def acquire(self, client_id: str) -> bool:
        """尝试获取一次调用许可，返回 True 表示允许"""
        now = time.time()
        if client_id not in self._clients:
            self._clients[client_id] = deque()

        timestamps = self._clients[client_id]

        # 清理过期记录
        while timestamps and now - timestamps[0] > self.window:
            timestamps.popleft()

        if len(timestamps) < self.max_calls:
            timestamps.append(now)
            return True

        logger.warning("速率限制触发: %s (%d 次/%ds)", client_id, len(timestamps), self.window)
        return False

    def remaining(self, client_id: str) -> int:
        """查询剩余可用次数"""
        if client_id not in self._clients:
            return self.max_calls
        now = time.time()
        timestamps = self._clients[client_id]
        while timestamps and now - timestamps[0] > self.window:
            timestamps.popleft()
        return max(0, self.max_calls - len(timestamps))


# 全局实例
_default_limiter = RateLimiter()


def get_rate_limiter() -> RateLimiter:
    return _default_limiter
