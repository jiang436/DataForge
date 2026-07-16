"""
LLM JSON 输出解析器 — 统一的容错解析工具。

问题: LLM 输出的 JSON 格式多变（markdown 代码块、裸 JSON、嵌套对象），
      4 个模块各自手写正则解析，脆弱且不一致。
方案: 集中的 parse_llm_json() 提供多层回退解析 + 统一错误信息。

用法:
    from backend.utils.json_parser import parse_llm_json
    data = parse_llm_json(llm_output)
"""

import json
import logging
import re

logger = logging.getLogger(__name__)


def parse_llm_json(content: str, description: str = "LLM output") -> dict | list:
    """
    容错解析 LLM 输出的 JSON，内置多层回退。

    尝试顺序:
      1. ```json / ``` 代码块提取
      2. 直接 json.loads
      3. 搜索最外层完整 JSON 对象 (平衡括号匹配)
      4. 全部失败 → 抛出 ValueError（调用方自行降级）

    Args:
        content:    LLM 原始输出文本
        description: 描述（用于错误日志）

    Returns:
        解析后的 dict 或 list

    Raises:
        ValueError: 所有解析路径均失败
    """
    if not content or not content.strip():
        raise ValueError(f"{description} 为空，无法解析")

    content = content.strip()

    # ─── 尝试 1: markdown 代码块 ───
    # 支持 ```json ... ``` 和 ``` ... ``` 两种形式
    block_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", content, re.DOTALL)
    if block_match:
        block_content = block_match.group(1).strip()
        try:
            return json.loads(block_content)
        except json.JSONDecodeError:
            logger.debug("[json_parser] 代码块内 JSON 解析失败，继续回退")

    # ─── 尝试 2: 直接解析全文 ───
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        logger.debug("[json_parser] 直接 JSON 解析失败，继续回退")

    # ─── 尝试 3: 平衡括号匹配提取最外层 JSON 对象/数组 ───
    # 比原来的简单正则 \{...\} 更可靠，支持嵌套对象
    extracted = _extract_balanced_json(content)
    if extracted is not None:
        try:
            return json.loads(extracted)
        except json.JSONDecodeError:
            logger.debug("[json_parser] 平衡匹配提取的 JSON 解析失败，继续回退")

    # ─── 全部失败 ───
    raise ValueError(
        f"{description} 无法解析为 JSON（已尝试: 代码块→直接解析→平衡匹配）。"
        f"原始输出前 300 字符: {content[:300]}"
    )


def _extract_balanced_json(text: str) -> str | None:
    """
    通过平衡括号匹配提取最外层 JSON 对象或数组。

    比正则 `{...}` 更可靠:
      - 正确处理嵌套对象 { "a": { "b": 1 } }
      - 正确处理字符串内的花括号
      - 支持数组根类型 [ ... ]
    """
    # 找到第一个 JSON 起始字符
    start_idx = _find_json_start(text)
    if start_idx == -1:
        return None

    open_char = text[start_idx]
    close_char = "}" if open_char == "{" else "]"

    in_string = False
    escape = False
    depth = 0

    for i in range(start_idx, len(text)):
        ch = text[i]

        if escape:
            escape = False
            continue

        if ch == "\\":
            escape = True
            continue

        if ch == '"':
            in_string = not in_string
            continue

        if in_string:
            continue

        if ch == open_char:
            depth += 1
        elif ch == close_char:
            depth -= 1
            if depth == 0:
                return text[start_idx : i + 1]

    return None


def _find_json_start(text: str) -> int:
    """找到第一个 { 或 [ 的位置（跳过字符串内的）"""
    in_string = False
    escape = False
    for i, ch in enumerate(text):
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if not in_string and ch in ("{", "["):
            return i
    return -1
