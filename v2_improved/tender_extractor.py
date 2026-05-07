# tender_extractor.py
# 这个文件负责：从招标文件里挖出关键信息

import json
import re
from typing import Any
from openai import OpenAI
import instructor
from models import TenderInfo
from config import DEEPSEEK_BASE_URL, DEEPSEEK_MODEL, LLM_TIMEOUT_SECONDS
from retry_handler import with_retry
from logger_config import logger


# ========== 工具函数 ==========
def get_qualification_snippet(full_text: str, max_chars: int = 5000) -> str:
    """从大段文字里截取'资格要求'附近的内容"""
    logger.info("开始截取资格要求片段")
    keywords = ["投标人资格要求", "资格要求", "投标人资格", "资质要求"]
    cleaned = re.sub(r"\n{2,}", "\n", full_text)
    lower_text = cleaned.lower()

    for kw in keywords:
        idx = lower_text.find(kw.lower())
        if idx != -1:
            start = max(0, idx - 300)
            end = min(len(cleaned), idx + max_chars)
            logger.info(f"找到关键词「{kw}」，截取位置 {start}-{end}")
            return cleaned[start:end]

    logger.info("未找到资格要求关键词，返回原文前段")
    return cleaned[:max_chars]


# ========== 兜底提取（AI失败时用） ==========
def fallback_extract_core_fields(raw_text: str) -> dict[str, Any]:
    """AI罢工时的土办法提取"""
    logger.info("开始兜底提取（正则）")
    
    def pick(pattern: str) -> str | None:
        m = re.search(pattern, raw_text, flags=re.I)
        return m.group(1).strip() if m else None

    project_name = pick(
        r"(?:项目名称|項目名稱|项目名|項目名|採購案名|標案名稱|案名|采购项目名称)\s*[:：]\s*([^\n\r]+)"
    )
    
    capital_requirement = pick(
        r"((?:注册资本|註冊資本|實收資本額|实收资本额|資本額|资本额|資本金|资本金)"
        r"(?:要求|不低于|不得低於|不低於|不少于|不少於)?[^。\n\r]{0,80})"
    )
    
    bid_deadline = pick(
        r"(?:投标截止时间|投標截止時間|投标截止日期|投標截止日期|截止时间|截止時間|截止日期|投標截止日)\s*[:：]\s*([^\n\r]+)"
    )

    cert_candidates = re.findall(
        r"(?:须具备|須具備|具备|具備|拥有|擁有|提供|需具有|應具有|应具有)"
        r"[^。\n\r]{0,80}"
        r"(?:证书|證書|资质|資質|许可证|許可證|認證|认证)",
        raw_text,
        flags=re.I,
    )
    certificates = list(dict.fromkeys([c.strip() for c in cert_candidates if c.strip()]))[:5]

    result = {
        "项目名称": project_name,
        "注册资本要求": capital_requirement,
        "必须具备的资质证书": certificates,
        "投标截止时间": bid_deadline,
    }
    
    logger.info(f"兜底提取完成：项目名={'有' if project_name else '无'}，"
                f"注册资本={'有' if capital_requirement else '无'}，"
                f"证书数={len(certificates)}")
    
    return result


# ========== AI提取（主力：Instructor 结构化输出）==========
@with_retry
def extract_core_fields_structured(raw_text: str, api_key: str) -> dict[str, Any]:
    """
    用 Instructor 结构化提取标书要求
    保证输出格式100%正确
    """
    logger.info(f"开始结构化提取标书要求，文本长度: {len(raw_text)} 字符")
    
    client = instructor.from_openai(
        OpenAI(
            api_key=api_key,
            base_url=DEEPSEEK_BASE_URL,
            timeout=LLM_TIMEOUT_SECONDS,
            max_retries=0,
        )
    )
    
    # ===== 向量检索相关段落 =====
    from vector_store import search_relevant
    relevant_chunks = search_relevant(raw_text, "投标人资格要求 注册资本 资质证书 截止时间")
    relevant_text = "\n".join(relevant_chunks)[:8000]
    logger.info(f"检索到 {len(relevant_chunks)} 个相关段落，共 {len(relevant_text)} 字")
    
    prompt = f"""
你是招投标信息抽取助手。请从下面原始文本中精准提取以下字段：
- 项目名称
- 注册资本要求
- 必须具备的资质证书（列表）
- 投标截止时间

要求：
1) 不确定时返回 null 或空列表，不要臆造。
2) 资质证书只保留证书/资质名称，不要附带解释。

原始文本：
{relevant_text}
"""
    
    logger.info("发送请求到 DeepSeek API（Instructor 模式）")
    
    response = client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        temperature=0,
        response_model=TenderInfo,
        messages=[
            {"role": "system", "content": "你是严谨的信息抽取引擎。"},
            {"role": "user", "content": prompt},
        ],
    )
    
    result = {
        "项目名称": response.项目名称,
        "注册资本要求": response.注册资本要求,
        "必须具备的资质证书": response.必须具备的资质证书,
        "投标截止时间": response.投标截止时间,
    }
    
    logger.info(f"结构化提取完成：项目名={'有' if result['项目名称'] else '无'}，"
                f"注册资本={'有' if result['注册资本要求'] else '无'}，"
                f"证书数={len(result['必须具备的资质证书'])}")
    
    return result


# ========== 兼容旧调用 ==========
def extract_core_fields_with_ai(raw_text: str, api_key: str) -> dict[str, Any]:
    """兼容旧接口，内部调用结构化版本"""
    return extract_core_fields_structured(raw_text, api_key)