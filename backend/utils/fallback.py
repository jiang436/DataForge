"""
结构化降级/回退模式


提供装饰器和函数，任何函数调用失败时自动降级到备用方案。
"""

import functools
import logging
import time
from collections.abc import Callable
from typing import TypeVar

logger = logging.getLogger("utils")

T = TypeVar("T")


def with_fallback(
    *fallbacks: Callable[..., T],
    max_retries: int = 1,
    retry_delay: float = 0.5,
):
    """
    降级装饰器: 主函数失败 → 依次尝试备用函数

    用法:
        def primary(): ...
        def backup():  ...
        def last_resort(): ...

        @with_fallback(backup, last_resort)
        def fetch_data():
            return primary()
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> T:
            last_error = None

            # 尝试主函数（含重试）
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_error = e
                    if attempt < max_retries:
                        logger.debug("重试 %d/%d: %s", attempt + 1, max_retries, e)
                        time.sleep(retry_delay)

            logger.warning("主函数失败，尝试降级: %s", last_error)

            # 依次尝试备用函数
            for i, fallback_fn in enumerate(fallbacks):
                try:
                    result = fallback_fn(*args, **kwargs)
                    logger.info("降级成功: 方案 %d", i + 1)
                    return result
                except Exception as e:
                    logger.warning("降级 %d 失败: %s", i + 1, e)

            raise RuntimeError(
                f"所有方案均失败（主函数 + {len(fallbacks)} 个降级）。最后错误: {last_error}"
            )

        return wrapper

    return decorator


def safe_call(
    fn: Callable[..., T],
    *args,
    default: T = None,
    log_error: bool = True,
    **kwargs,
) -> T:
    """
    安全调用: 函数异常时返回默认值，永不崩溃

    用法:
        result = safe_call(may_fail, arg1, arg2, default=[])
    """
    try:
        return fn(*args, **kwargs)
    except Exception as e:
        if log_error:
            logger.warning("安全调用捕获异常: %s，返回默认值", e)
        return default


def retry_on_failure(
    max_retries: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
):
    """
    重试装饰器: 指数退避重试

    用法:
        @retry_on_failure(max_retries=3, delay=0.5)
        def call_api():
            ...
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            current_delay = delay
            last_error = None

            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_error = e
                    if attempt < max_retries:
                        logger.debug(
                            "重试 %d/%d (等待 %.1fs): %s",
                            attempt + 1,
                            max_retries,
                            current_delay,
                            e,
                        )
                        time.sleep(current_delay)
                        current_delay *= backoff

            raise RuntimeError(f"重试 {max_retries} 次后仍失败。最后错误: {last_error}")

        return wrapper

    return decorator
