"""
智能文本截断

参考: tradingagents/agents/utils/memory.py → _smart_text_truncation()

三层降级:
  1. 句子边界截断（按 。！？）
  2. 段落边界截断（按 \\n\\n）
  3. 硬截断（保留首尾关键信息）
"""

import logging

logger = logging.getLogger("utils")


def smart_truncate(text: str, max_length: int = 8192) -> tuple[str, bool]:
    """
    智能文本截断，保持语义完整性

    参考: memory.py → _smart_text_truncation()

    Args:
        text:       原始文本
        max_length: 最大字符数

    Returns:
        (截断后文本, 是否被截断)
    """
    if len(text) <= max_length:
        return text, False

    # ─── 1. 句子边界截断 ───
    sentences = text.split("。")
    if len(sentences) > 1:
        truncated = ""
        for s in sentences:
            if len(truncated + s + "。") <= max_length - 50:
                truncated += s + "。"
            else:
                break
        if len(truncated) > max_length // 2:
            logger.info("句子边界截断: %d → %d 字符", len(text), len(truncated))
            return truncated, True

    # ─── 2. 段落边界截断 ───
    paragraphs = text.split("\n")
    if len(paragraphs) > 1:
        truncated = ""
        for p in paragraphs:
            if len(truncated + p + "\n") <= max_length - 50:
                truncated += p + "\n"
            else:
                break
        if len(truncated) > max_length // 2:
            logger.info("段落边界截断: %d → %d 字符", len(text), len(truncated))
            return truncated, True

    # ─── 3. 硬截断：保留首尾关键信息 ───
    half = max_length // 2
    result = text[:half] + "\n...[内容截断]...\n" + text[-half + 100 :]
    logger.warning("硬截断: %d → %d 字符", len(text), len(result))
    return result, True
