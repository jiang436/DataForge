"""
共享线程池 — 统一管理后台任务执行

替代 chat.py 中每请求新建 ThreadPoolExecutor 的做法。
最大线程数 = cpu_count * 2，避免并发请求时无限创建线程。
"""

import os
from concurrent.futures import ThreadPoolExecutor

_executor: ThreadPoolExecutor | None = None


def get_executor() -> ThreadPoolExecutor:
    """获取全局共享线程池（惰性初始化）"""
    global _executor
    if _executor is None:
        max_workers = min(32, (os.cpu_count() or 4) * 2)
        _executor = ThreadPoolExecutor(max_workers=max_workers)
    return _executor


def shutdown_executor():
    """关闭线程池（应用停止时调用）"""
    global _executor
    if _executor is not None:
        _executor.shutdown(wait=True)
        _executor = None
