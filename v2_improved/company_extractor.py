# company_extractor.py
# 这个文件负责：从公司资质PDF里挖出注册资本和证书
# 想改提取内容？改这里的AI提示词

import json
import re
from typing import Any
from openai import OpenAI
from config import DEEPSEEK_BASE_URL, DEEPSEEK_MODEL, LLM_TIMEOUT_SECONDS
from retry_handler import with_retry

@with_retry  # ⭐ 加这一行就行

# ========== 兜底提取 ==========
def fallback_extract_company_profile(raw_text: str) -> dict[str, Any]:
    """AI罢工时的土办法"""
    capital_match = re.search(r"(注册资本[^。\n\r]{0,40})", raw_text, flags=re.I)
    cert_candidates = re.findall(
        r"(?:资质证书|资质等级|安全生产许可证|营业执照)[^。\n\r]{0,20}",
        raw_text,
        flags=re.I,
    )
    certs = list(dict.fromkeys([c.strip() for c in cert_candidates if c.strip()]))[:8]
    return {
        "公司注册资本": capital_match.group(1).strip() if capital_match else None,
        "持有的证书列表": certs,
    }

# ========== AI提取（主力） ==========
def extract_company_profile_with_ai(raw_text: str, api_key: str) -> dict[str, Any]:
    """
    用AI从公司资质文件提取信息
    返回：公司注册资本、持有的证书列表
    """
    client = OpenAI(
        api_key=api_key,
        base_url=DEEPSEEK_BASE_URL,
        timeout=LLM_TIMEOUT_SECONDS,
        max_retries=0,  # ← 加这行
    )
    
    # ===== 想改AI提取的内容？改下面这个提示词 =====
    prompt = f"""
你是企业资质信息抽取助手。请从企业资质证明文本中提取以下字段，并仅输出 JSON 对象：
- 公司注册资本: string | null
- 持有的证书列表: string[] (若无则 [])

要求：
1) 严禁输出 JSON 以外内容。
2) 不确定时返回 null 或 []，不要编造。
3) 证书列表只保留证书/资质名称。

文本：
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
    certs = data.get("持有的证书列表", [])
    if not isinstance(certs, list):
        certs = []
    return {
        "公司注册资本": data.get("公司注册资本"),
        "持有的证书列表": [str(c).strip() for c in certs if str(c).strip()],
    }