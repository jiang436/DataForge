"""
YAML 轻量级结构化协议解析器

借鉴: data_analysis_agent 的 YAML 协议模式 —
      LLM 使用 YAML 格式输出（而非 JSON），同时包含
      自然语言 + 结构化字段 + 代码块，更自然且无需转义多行字符串。

适用场景:
  - Chart Agent 备选逻辑: LLM 需同时输出 reasoning + chart_type + code
  - 任意需要 LLM 输出混合内容的场景

设计:
  - 主解析: yaml.safe_load()（需要 PyYAML 安装）
  - 降级: 正则表达式提取 YAML 块 + 简单键值对解析
  - 零依赖风险: yaml 导入失败时自动降级

用法:
    from backend.utils.yaml_parser import parse_yaml_response
    result = parse_yaml_response(llm_output)
    # result = {"action": "generate_code", "reasoning": "...", "code": "..."}
"""

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# ─── PyYAML 可选依赖 ───
try:
    import yaml
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False
    logger.debug("PyYAML 未安装，使用内建降级解析器（功能受限）")


def parse_yaml_response(
    text: str,
    fallback: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    从 LLM 输出中解析 YAML 格式的结构化内容。

    支持的格式:
      1. 纯 YAML 文档（以 --- 开头或直接是键值对）
      2. Markdown 代码块中的 YAML（```yaml ... ```）
      3. 内联 YAML 片段（混在自然语言中）

    Args:
        text:      LLM 原始输出文本
        fallback:  解析失败时的默认返回值

    Returns:
        解析后的 dict。解析失败返回 fallback 或空 dict。
    """
    if not text or not text.strip():
        return fallback or {}

    # ─── 尝试 1: 提取 Markdown YAML 代码块 ───
    yaml_block = _extract_fenced_block(text, "yaml")
    if yaml_block:
        result = _try_parse_yaml(yaml_block)
        if result:
            return result

    # ─── 尝试 2: 提取任意代码块中的 YAML 内容 ───
    any_block = _extract_fenced_block(text)
    if any_block and _looks_like_yaml(any_block):
        result = _try_parse_yaml(any_block)
        if result:
            return result

    # ─── 尝试 3: 直接解析全文 ───
    result = _try_parse_yaml(text)
    if result:
        return result

    # ─── 降级: 正则键值对解析 ───
    result = _fallback_key_value_parse(text)
    if result:
        logger.debug("[YAML Parser] 降级正则解析成功，提取 %d 个字段", len(result))
        return result

    # ─── 最终降级 ───
    logger.warning("[YAML Parser] 所有解析路径均失败，返回 fallback")
    return fallback or {}


def extract_yaml_and_code(
    text: str,
) -> tuple[dict[str, Any], str | None]:
    """
    从 LLM 输出中同时提取 YAML 元数据和代码块。

    典型用法（Chart Agent）:
        meta, code = extract_yaml_and_code(llm_response)
        # meta = {"chart_type": "bar", "reasoning": "数据适合柱状图"}
        # code = "import plotly.graph_objects as go\\n..."

    Args:
        text: LLM 原始输出

    Returns:
        (metadata_dict, code_string_or_None)
    """
    meta = parse_yaml_response(text)

    # 提取代码块（python 或通用）
    code = (
        _extract_fenced_block(text, "python")
        or _extract_fenced_block(text, "py")
        or _extract_fenced_block(text, "code")
        or _extract_fenced_block(text)  # 任意代码块
    )

    return meta, code


def format_yaml_prompt(
    fields: dict[str, str],
    include_code_block: bool = False,
) -> str:
    """
    生成 YAML 格式的输出指令（注入 LLM prompt 使用）。

    Args:
        fields:              期望的字段 {name: description}
        include_code_block:  是否包含代码块字段

    Returns:
        格式化后的 YAML 输出指令文本
    """
    lines = [
        "请使用 YAML 格式输出你的分析结果（不要用 JSON）：",
        "",
        "```yaml",
    ]
    for name, desc in fields.items():
        lines.append(f"{name}: <{desc}>")

    if include_code_block:
        lines.append("code: |")
        lines.append("  <你的代码>")

    lines.append("```")
    lines.append("")
    lines.append("注意：YAML 格式中多行文本使用 `|` 标记，无需转义引号和换行。")

    return "\n".join(lines)


# ─── 内部辅助函数 ───


def _try_parse_yaml(text: str) -> dict[str, Any] | None:
    """尝试用 PyYAML 解析，失败返回 None"""
    if not _HAS_YAML:
        return _fallback_yaml_parse(text)

    try:
        result = yaml.safe_load(text)
        if isinstance(result, dict):
            return _normalize_values(result)
        if isinstance(result, list) and len(result) > 0 and isinstance(result[0], dict):
            # YAML 文档列表 → 取第一个
            return _normalize_values(result[0])
        return None
    except yaml.YAMLError as e:
        logger.debug("[YAML Parser] PyYAML 解析失败: %s", e)
        return None
    except Exception as e:
        logger.debug("[YAML Parser] 解析异常: %s", e)
        return None


def _fallback_yaml_parse(text: str) -> dict[str, Any] | None:
    """
    无 PyYAML 时的简化 YAML 解析器。

    仅支持单层键值对:
      key: value
      key: |
        multiline
        value
    """
    lines = text.strip().split("\n")
    result: dict[str, Any] = {}
    current_key: str | None = None
    current_value: list[str] = []
    in_multiline = False

    for line in lines:
        # 跳过注释和空行
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            if in_multiline and not stripped:
                current_value.append("")
            continue

        # 检测键值对: key: value
        kv_match = re.match(r"^([a-zA-Z_][a-zA-Z0-9_]*)\s*:\s*(.*)", line)
        if kv_match and not line.startswith(" ") and not line.startswith("\t"):
            # 保存上一个键值对
            if current_key is not None:
                result[current_key] = _finalize_value(current_value, in_multiline)

            current_key = kv_match.group(1)
            value_part = kv_match.group(2).strip()

            if value_part in ("|", "|-)", ">-"):
                # 多行文本标记
                in_multiline = True
                current_value = []
            elif value_part:
                in_multiline = False
                current_value = [value_part]
            else:
                in_multiline = False
                current_value = []
        elif current_key is not None:
            # 续行（多行文本内容）
            if in_multiline:
                # 去除首层缩进
                unindented = re.sub(r"^  ", "", line) if line.startswith("  ") else stripped
                current_value.append(unindented)
            else:
                current_value.append(stripped)

    # 保存最后一个键值对
    if current_key is not None:
        result[current_key] = _finalize_value(current_value, in_multiline)

    return result if result else None


def _finalize_value(parts: list[str], is_multiline: bool) -> str:
    """将值片段合并为最终字符串"""
    if not parts:
        return ""
    if is_multiline:
        return "\n".join(parts).strip()
    return " ".join(parts).strip()


def _extract_fenced_block(text: str, lang: str | None = None) -> str | None:
    """
    提取 Markdown 围栏代码块内容。

    Args:
        text: 源文本
        lang: 可选的语言标识符（如 "yaml", "python"），None 匹配任意代码块

    Returns:
        代码块内容（不含围栏），或 None
    """
    if lang:
        pattern = rf"```{lang}\s*\n(.*?)```"
    else:
        pattern = r"```(?:\w*)\s*\n(.*?)```"

    matches = re.findall(pattern, text, re.DOTALL)
    if matches:
        return matches[0].strip()
    return None


def _looks_like_yaml(text: str) -> bool:
    """启发式判断文本是否为 YAML 格式"""
    # YAML 特征: 有 key: value 行，没有 JSON 花括号
    if "{" in text and '"' in text:
        return False  # 可能是 JSON
    return bool(re.search(r"^[a-zA-Z_][a-zA-Z0-9_]*\s*:", text, re.MULTILINE))


def _fallback_key_value_parse(text: str) -> dict[str, Any] | None:
    """
    正则降级：匹配 key: value 模式。

    比 _fallback_yaml_parse 更宽松，适用于高度非标准输出。
    """
    result: dict[str, Any] = {}

    # 匹配模式: key: value (value 可以是引号字符串、单词、或到行尾)
    pattern = r"^([a-zA-Z_][a-zA-Z0-9_]*)\s*:\s*(.+)$"
    matches = re.findall(pattern, text, re.MULTILINE)

    if len(matches) < 2:
        return None

    for key, value in matches:
        if key.lower() in ("code", "output", "content"):
            continue  # 代码块单独处理
        # 清理引号
        cleaned = value.strip().strip('"').strip("'")
        result[key] = cleaned

    return result if len(result) >= 2 else None


def _normalize_values(data: dict) -> dict[str, Any]:
    """将 YAML 解析结果中的值规范化（去 None，str 化）"""
    result = {}
    for k, v in data.items():
        if v is None:
            result[k] = ""
        elif isinstance(v, (int, float, bool)):
            result[k] = v  # 保留原始类型
        elif isinstance(v, (list, dict)):
            result[k] = v  # 保留嵌套结构
        else:
            result[k] = str(v)
    return result
