# tender_extractor.py
# 这个文件负责：从招标文件里挖出关键信息
# 想改提取哪些字段？想改AI提示词？来这里

import json
import re
from typing import Any
from openai import OpenAI
from config import DEEPSEEK_BASE_URL, DEEPSEEK_MODEL, LLM_TIMEOUT_SECONDS
from retry_handler import with_retry

@with_retry  # ⭐ 加这一行就行



# ========== 工具函数 ==========
def get_qualification_snippet(full_text: str, max_chars: int = 5000) -> str:
    """从大段文字里截取'资格要求'附近的内容"""
    keywords = ["投标人资格要求", "资格要求", "投标人资格", "资质要求"]
    cleaned = re.sub(r"\n{2,}", "\n", full_text)
    lower_text = cleaned.lower()

    for kw in keywords:
        idx = lower_text.find(kw.lower())
        if idx != -1:
            start = max(0, idx - 300)
            end = min(len(cleaned), idx + max_chars)
            return cleaned[start:end]

    return cleaned[:max_chars]

# ========== 兜底提取（AI失败时用） ==========
def fallback_extract_core_fields(raw_text: str) -> dict[str, Any]:
    """AI罢工时的土办法提取"""
    def pick(pattern: str) -> str | None:
        m = re.search(pattern, raw_text, flags=re.I)
        return m.group(1).strip() if m else None

    project_name = pick(r"(?:项目名称|项目名)\s*[:：]\s*([^\n\r]+)")
    capital_requirement = pick(r"((?:注册资本(?:金)?(?:要求)?)[^。\n\r]{0,50})")
    bid_deadline = pick(r"(?:投标截止时间|投标截止日期|截止时间)\s*[:：]\s*([^\n\r]+)")

    cert_candidates = re.findall(
        r"(?:须具备|具备|拥有|提供)[^。\n\r]{0,50}(?:证书|资质|许可证)[^。\n\r]{0,30}",
        raw_text,
        flags=re.I,
    )
    certificates = list(dict.fromkeys([c.strip() for c in cert_candidates if c.strip()]))[:5]

    return {
        "项目名称": project_name,
        "注册资本要求": capital_requirement,
        "必须具备的资质证书": certificates,
        "投标截止时间": bid_deadline,
    }

# ========== AI提取（主力） ==========
def extract_core_fields_with_ai(raw_text: str, api_key: str) -> dict[str, Any]:
    """
    用AI从招标文件提取核心字段
    返回字段：项目名称、注册资本要求、资质证书列表、投标截止时间
    """
    client = OpenAI(
        api_key=api_key,
        base_url=DEEPSEEK_BASE_URL,
        timeout=LLM_TIMEOUT_SECONDS,
        max_retries=0  # ← 加这一行，关掉OpenAI自带重试
    )
    
    # ===== 想改AI提取的内容？改下面这个提示词 =====
    prompt = f"""
你是招投标信息抽取助手。请从下面原始文本中精准提取以下字段，并仅输出一个 JSON 对象：
- 项目名称: string | null
- 注册资本要求: string | null
- 必须具备的资质证书: string[]（若无则 []）
- 投标截止时间: string | null

要求：
1) 严禁输出除 JSON 外的任何文字。
2) 不确定时返回 null，不要臆造。
3) "必须具备的资质证书"只保留证书/资质名称，不要附带解释。

原始文本：
{raw_text[:12000]}
"""
    # ===== 提示词结束 =====
    
    response = client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": "你是严谨的信息抽取引擎，只返回合法 JSON。"},
            {"role": "user", "content": prompt},
        ],
    )
    content = response.choices[0].message.content or "{}"
    data = json.loads(content)
    return {
        "项目名称": data.get("项目名称"),
        "注册资本要求": data.get("注册资本要求"),
        "必须具备的资质证书": data.get("必须具备的资质证书", []),
        "投标截止时间": data.get("投标截止时间"),
    }