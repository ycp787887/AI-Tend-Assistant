# company_extractor.py
# 这个文件负责：从公司资质PDF里挖出注册资本和证书

import re
from typing import Any
from openai import OpenAI
import instructor
from models import CompanyProfile
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


# ========== AI提取（主力：Instructor 结构化输出）==========
@with_retry
def extract_company_profile_structured(raw_text: str, api_key: str) -> dict[str, Any]:
    """
    用 Instructor 结构化提取公司资质
    保证输出格式100%正确
    """
    logger.info(f"开始结构化提取公司资质，文本长度: {len(raw_text)} 字符")
    
    client = instructor.from_openai(
        OpenAI(
            api_key=api_key,
            base_url=DEEPSEEK_BASE_URL,
            timeout=LLM_TIMEOUT_SECONDS,
            max_retries=0,
        )
    )
    
    prompt = f"""
你是企业资质信息抽取助手。请从企业资质证明文本中提取以下字段：
- 公司注册资本
- 持有的证书列表

要求：
1) 不确定时返回 null 或空列表，不要编造。
2) 证书列表只保留证书/资质名称。

文本：
{raw_text[:12000]}
"""
    
    logger.info("发送请求到 DeepSeek API（Instructor 模式）")
    
    response = client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        temperature=0,
        response_model=CompanyProfile,
        messages=[
            {"role": "system", "content": "你是严谨的信息抽取引擎。"},
            {"role": "user", "content": prompt},
        ],
    )
    
    result = {
        "公司注册资本": response.公司注册资本,
        "持有的证书列表": response.持有的证书列表,
    }
    
    logger.info(f"公司资质提取完成：注册资本={'有' if result['公司注册资本'] else '无'}，"
                f"证书数={len(result['持有的证书列表'])}")
    
    logger.info(f"公司原始文本前500字: {raw_text[:500]}")
    logger.info(f"提取结果: {result}")

    return result
    

# ========== 兼容旧调用 ==========
def extract_company_profile_with_ai(raw_text: str, api_key: str) -> dict[str, Any]:
    """兼容旧接口，内部调用结构化版本"""
    return extract_company_profile_structured(raw_text, api_key)