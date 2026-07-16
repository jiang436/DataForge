"""
Prompt 模板加载器

所有 Agent 的 system prompt 集中管理在 backend/prompts/ 目录下。
非开发人员可以直接编辑 .md 文件调优 prompt，无需改代码。

用法:
    from backend.prompts import load_prompt
    prompt = load_prompt("sql_agent")
"""

from pathlib import Path

_PROMPT_DIR = Path(__file__).parent
_cache: dict[str, str] = {}


def load_prompt(name: str) -> str:
    """加载指定名称的 prompt 模板"""
    if name not in _cache:
        path = _PROMPT_DIR / f"{name}.md"
        if not path.exists():
            raise FileNotFoundError(f"Prompt 文件不存在: {path}")
        _cache[name] = path.read_text(encoding="utf-8")
    return _cache[name]


def reload_prompts():
    """重新加载所有 prompt（热更新用）"""
    _cache.clear()
