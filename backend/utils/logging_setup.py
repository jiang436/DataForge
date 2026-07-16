"""
日志系统初始化

参考: tradingagents/utils/logging_init.py

在应用启动时配置统一日志格式。
"""

import logging
import logging.handlers
import os
import sys


def setup_logging(
    level: str = "INFO",
    log_dir: str = "logs",
    enable_file: bool = True,
) -> None:
    """
    初始化项目日志系统
    """
    log_level = getattr(logging, level.upper(), logging.INFO)

    # ─── Windows 终端 UTF-8 支持 ───
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    root = logging.getLogger()
    root.setLevel(log_level)
    root.handlers.clear()

    # ─── 控制台 handler ───
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(log_level)
    console.setFormatter(_ColorFormatter() if _is_tty() else _PlainFormatter())
    root.addHandler(console)

    # ─── 文件 handler ───
    if enable_file:
        os.makedirs(log_dir, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            filename=os.path.join(log_dir, "dataforge.log"),
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setLevel(log_level)
        file_handler.setFormatter(_PlainFormatter())
        root.addHandler(file_handler)

    # ─── 降低第三方库日志噪音 ───
    for lib in ("httpx", "urllib3", "openai", "chromadb"):
        logging.getLogger(lib).setLevel(logging.WARNING)

    # ─── 模块日志器 ───
    for module in ("agents", "tools", "graph", "dataflows", "api"):
        logging.getLogger(module).setLevel(log_level)


def get_logger(name: str) -> logging.Logger:
    """获取模块日志器"""
    return logging.getLogger(name)


def _is_tty() -> bool:
    """检测是否为交互终端（支持彩色输出）"""
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


class _ColorFormatter(logging.Formatter):
    """彩色控制台格式化器"""

    COLORS = {
        logging.DEBUG: "\033[36m",  # 青色
        logging.INFO: "\033[32m",  # 绿色
        logging.WARNING: "\033[33m",  # 黄色
        logging.ERROR: "\033[31m",  # 红色
        logging.CRITICAL: "\033[41m",  # 红色背景
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelno, "")
        fmt = (
            f"\033[90m%(asctime)s\033[0m "
            f"{color}[%(levelname)-5s]\033[0m "
            f"\033[36m%(name)s\033[0m: "
            f"%(message)s"
        )
        formatter = logging.Formatter(fmt, datefmt="%H:%M:%S")
        return formatter.format(record)


class _PlainFormatter(logging.Formatter):
    """纯文本格式化器（文件日志用）"""

    def format(self, record: logging.LogRecord) -> str:
        fmt = "%(asctime)s [%(levelname)-5s] %(name)s: %(message)s"
        formatter = logging.Formatter(fmt, datefmt="%Y-%m-%d %H:%M:%S")
        return formatter.format(record)
