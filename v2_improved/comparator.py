# comparator.py
# 这个文件是核心！负责比较标书要求和公司情况
# 想加新的比较项？想改达标判断逻辑？来这里

import re
from typing import Any

# ========== 单位换算 ==========
def parse_capital_to_wan(text: str | None) -> float | None:
    """
    把各种注册资本格式统一换算成"万元"
    500万 → 500
    0.5亿 → 5000
    5000000元 → 500
    """
    if not text:
        return None

    normalized = text.replace(",", "").replace("，", "").strip()
    m = re.search(r"(\d+(?:\.\d+)?)", normalized)
    if not m:
        return None

    value = float(m.group(1))
    if "亿" in normalized:
        return value * 10000
    if "万" in normalized:
        return value
    if "元" in normalized:
        return value / 10000
    return value

def normalize_certs(certs_text: str) -> list[str]:
    """把证书字符串切成列表"""
    parts = re.split(r"[,\n;；、，]+", certs_text)
    return [p.strip() for p in parts if p.strip()]

# ========== 核心比较函数 ==========
def compare_with_company_profile(core: dict[str, Any], company_profile: dict[str, Any]) -> dict[str, Any]:
    """
    比较标书要求和公司资质
    返回比较结果字典
    """
    # 1. 比较注册资本
    required_capital_text = core.get("注册资本要求")
    required_capital_wan = parse_capital_to_wan(required_capital_text)
    company_capital_text = company_profile.get("公司注册资本")
    company_capital_wan = parse_capital_to_wan(company_capital_text)

    # 2. 比较资质证书
    required_certs = core.get("必须具备的资质证书", [])
    if not isinstance(required_certs, list):
        required_certs = []
    required_certs = [str(c).strip() for c in required_certs if str(c).strip()]

    company_certs_raw = company_profile.get("持有的证书列表", [])
    if isinstance(company_certs_raw, list):
        company_certs = [str(c).strip() for c in company_certs_raw if str(c).strip()]
    else:
        company_certs = normalize_certs(str(company_certs_raw))
    
    # 找出缺失的证书
    missing_certs: list[str] = []
    for req in required_certs:
        if not any(req in own or own in req for own in company_certs):
            missing_certs.append(req)

    # 3. 判断注册资本是否达标
    capital_not_met = (
        required_capital_wan is not None
        and company_capital_wan is not None
        and required_capital_wan > company_capital_wan
    )

    return {
        "capital_not_met": capital_not_met,
        "required_capital_text": required_capital_text,
        "required_capital_wan": required_capital_wan,
        "company_capital_text": company_capital_text,
        "company_capital_wan": company_capital_wan,
        "company_certs": company_certs,
        "missing_certs": missing_certs,
    }