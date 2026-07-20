"""
工具调用日志装饰器


为 @tool 函数添加自动日志记录：开始、成功、失败、耗时。
"""

import functools
import logging
import time

logger = logging.getLogger("tools")


def log_tool_call(tool_name: str = "", log_args: bool = False):
    """
    工具调用日志装饰器

    Args:
        tool_name: 工具名称（不传则用函数名）
        log_args:  是否记录参数（数据较大时可关闭）

    用法:
        @tool
        @log_tool_call(tool_name="execute_sql")
        def execute_sql(sql: str) -> str:
            ...
    """

    def decorator(func):
        name = tool_name or func.__name__

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            t0 = time.time()

            if log_args:
                args_str = ", ".join(
                    [str(a)[:200] for a in args]
                    + [f"{k}={str(v)[:200]}" for k, v in kwargs.items()]
                )
                logger.info("[%s] 调用: %s", name, args_str)
            else:
                logger.info("[%s] 开始执行", name)

            try:
                result = func(*args, **kwargs)
                elapsed = time.time() - t0
                result_len = len(str(result)) if result else 0
                logger.info("[%s] 完成 (%.2fs, 返回 %d 字符)", name, elapsed, result_len)
                return result
            except Exception as e:
                elapsed = time.time() - t0
                logger.error("[%s] 失败 (%.2fs): %s", name, elapsed, str(e))
                raise

        return wrapper

    return decorator
