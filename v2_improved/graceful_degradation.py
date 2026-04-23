# graceful_degradation.py
"""
优雅降级：API 不可用时的备选方案
"""

def degrade_tender_extraction(text: str) -> dict:
    """
    AI 提取失败时，用正则兜底
    你已经有了 fallback_extract_core_fields，就是这个作用！
    """
    from tender_extractor import fallback_extract_core_fields
    return fallback_extract_core_fields(text)

def degrade_company_extraction(text: str) -> dict:
    """公司资质提取的兜底"""
    from company_extractor import fallback_extract_company_profile
    return fallback_extract_company_profile(text)

def degrade_risk_scan() -> list:
    """风险扫描的兜底"""
    return ["AI 暂时不可用，建议人工检查以下常见风险：霸王条款、不合理违约责任、付款条件"]