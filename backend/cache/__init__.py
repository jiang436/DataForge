"""
自适应缓存层

参考: tradingagents/dataflows/cache/adaptive.py 模式

缓存策略: 内存 → 文件 → 原始数据源
支持自动降级，任何一层失败都自动回退到下一层。
"""

from backend.cache.adaptive import AdaptiveCache

__all__ = ["AdaptiveCache"]
