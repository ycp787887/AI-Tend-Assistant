# company_extractor.py
# 这个文件负责：从公司资质PDF里挖出注册资本和证书
# 想改提取内容？改这里的AI提示词

import json
import re
from typing import Any, Generator
from openai import OpenAI
from config import DEEPSEEK_BASE_URL, DEEPSEEK_MODEL, LLM_TIMEOUT_SECONDS
from retry_handler import with_retry
from logger_config import logger


# ========== 兜底提取 ==========
def fallback_extract_company_profile(raw_text: str) -> dict[str, Any]:
    """AI罢工时的土办法"""
    logger.info("开始兜底提取公司资质")
    capital_match = re.search(r"(注册资本[^。\n\r]{0,40})", raw_text, flags=re.I)
    cert_candidates = re.findall(
        r"(?:资质证书|资质等级|安全生产许可证|营业执照)[^。\n\r]{0,20}",
        raw_text,
        flags=re.I,
    )
    certs = list(dict.fromkeys([c.strip() for c in cert_candidates if c.strip()]))[:8]
    result = {
        "公司注册资本": capital_match.group(1).strip() if capital_match else None,
        "持有的证书列表": certs,
    }
    logger.info(f"兜底提取完成：注册资本={'有' if result['公司注册资本'] else '无'}，证书数={len(certs)}")
    return result


# ========== AI提取流式版（主力）==========
@with_retry
def extract_company_profile_streaming(raw_text: str, api_key: str) -> Generator:
    """
    流式AI提取公司资质——逐字返回
    用于打字机效果展示
    """
    logger.info(f"开始流式AI提取公司资质，文本长度: {len(raw_text)} 字符")
    
    client = OpenAI(
        api_key=api_key,
        base_url=DEEPSEEK_BASE_URL,
        timeout=LLM_TIMEOUT_SECONDS,
        max_retries=0,
    )
    
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
    
    logger.info("发送流式请求到 DeepSeek API")
    response = client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        temperature=0,
        stream=True,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": "你是严谨的信息抽取引擎，只返回合法 JSON。"},
            {"role": "user", "content": prompt},
        ],
    )
    
    full_text = ""
    for chunk in response:
        if chunk.choices[0].delta.content:
            token = chunk.choices[0].delta.content
            full_text += token
            yield token, full_text
    
    logger.info(f"流式提取完成，总长度: {len(full_text)} 字符")


def parse_company_streaming_result(full_text: str) -> dict[str, Any]:
    """解析流式输出的最终结果"""
    import json
    try:
        data = json.loads(full_text)
    except json.JSONDecodeError:
        data = {}
    
    certs = data.get("持有的证书列表", [])
    if not isinstance(certs, list):
        certs = []
    
    result = {
        "公司注册资本": data.get("公司注册资本"),
        "持有的证书列表": [str(c).strip() for c in certs if str(c).strip()],
    }
    
    logger.info(f"流式结果解析完成：注册资本={'有' if result['公司注册资本'] else '无'}，"
                f"证书数={len(result['持有的证书列表'])}")
    
    return result


# ========== 保留原版（兼容性）==========
@with_retry
def extract_company_profile_with_ai(raw_text: str, api_key: str) -> dict[str, Any]:
    """原版非流式提取（保留作为备用）"""
    full_text = ""
    for _, current_text in extract_company_profile_streaming(raw_text, api_key):
        full_text = current_text
    return parse_company_streaming_result(full_text)