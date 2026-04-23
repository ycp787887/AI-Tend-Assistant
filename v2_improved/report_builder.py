# report_builder.py
# 这个文件负责：生成建议话术、构建表格数据、渲染HTML表格
# 想改建议话术模板？想改表格显示内容？来这里

from typing import Any
from html import escape
import streamlit as st

# ========== 建议话术生成 ==========
def build_advice(compare_result: dict[str, Any]) -> str:
    """
    根据比较结果生成建议话术
    想改话术内容？改这里的文字模板
    """
    messages: list[str] = []
    
    # 情况1：资质文件里没体现注册资本
    if compare_result["required_capital_wan"] is not None and compare_result["company_capital_wan"] is None:
        messages.append("资质文件中未体现注册资本，建议补充营业执照或工商信息页后再决策。")
    # 情况2：注册资本不达标
    elif compare_result["capital_not_met"]:
        messages.append("由于注册资本不足，建议联合投标或放弃本项目。")
    
    # 情况3：资质文件里没体现证书
    if compare_result["missing_certs"] and not compare_result["company_certs"]:
        messages.append("资质文件中未体现证书信息，建议补传资质附件后再评估是否投标。")
    # 情况4：证书有缺失
    elif compare_result["missing_certs"]:
        certs = "、".join(compare_result["missing_certs"])
        messages.append(f"资质证书存在缺失（{certs}），建议补证或寻找联合体伙伴。")
    
    # 情况5：都达标
    if not messages:
        messages.append("关键门槛基本满足，建议继续核验业绩条款、付款条款和违约责任条款。")
    
    return " ".join(messages)

# ========== 风险表格数据构建 ==========
def build_risk_rows(core: dict[str, Any], compare_result: dict[str, Any]) -> list[dict[str, str]]:
    """
    把比较结果转换成表格用的行数据
    想改表格里显示什么？改这里的字段
    """
    # 注册资本状态判断
    capital_missing_in_profile = (
        compare_result["required_capital_wan"] is not None and compare_result["company_capital_wan"] is None
    )
    if capital_missing_in_profile:
        capital_status = "⚠ 待核实"
        capital_risk = "资质文件中未体现，请核实"
    elif compare_result["capital_not_met"]:
        capital_status = "✖ 不达标"
        capital_risk = "注册资本不足"
    else:
        capital_status = "✅ 达标"
        capital_risk = "通过"

    # 证书状态判断
    certs_missing_in_profile = bool(core.get("必须具备的资质证书")) and not compare_result["company_certs"]
    if certs_missing_in_profile:
        cert_status = "⚠ 待核实"
        cert_risk = "资质文件中未体现，请核实"
    elif compare_result["missing_certs"]:
        cert_status = "✖ 有缺失"
        cert_risk = f"缺失：{'、'.join(compare_result['missing_certs'])}"
    else:
        cert_status = "✅ 达标"
        cert_risk = "通过"

    return [
        {
            "检查项": "注册资本",
            "标书要求": str(core.get("注册资本要求") or "未提取到"),
            "公司情况": str(compare_result["company_capital_text"] or "资质文件中未体现，请核实"),
            "结果": capital_status,
            "风险提示": capital_risk,
        },
        {
            "检查项": "资质证书",
            "标书要求": "、".join(core.get("必须具备的资质证书", [])) or "未提取到",
            "公司情况": "、".join(compare_result["company_certs"]) or "资质文件中未体现，请核实",
            "结果": cert_status,
            "风险提示": cert_risk,
        },
    ]

# ========== 表格渲染 ==========
def render_risk_table(risk_rows: list[dict[str, str]]) -> None:
    """在页面上渲染风险对比表格"""
    html = (
        '<table style="width:100%;border-collapse:collapse;font-size:14px;">'
        '<tr style="background:#f5f7fa;">'
        '<th style="border:1px solid #ddd;padding:8px;">检查项</th>'
        '<th style="border:1px solid #ddd;padding:8px;">标书要求</th>'
        '<th style="border:1px solid #ddd;padding:8px;">公司情况</th>'
        '<th style="border:1px solid #ddd;padding:8px;">结果</th>'
        '<th style="border:1px solid #ddd;padding:8px;">风险提示</th>'
        "</tr>"
    )
    for row in risk_rows:
        if "✖" in row["结果"]:
            color = "#d32f2f"
        elif "⚠" in row["结果"]:
            color = "#ed6c02"
        else:
            color = "#2e7d32"
        html += (
            "<tr>"
            f'<td style="border:1px solid #ddd;padding:8px;">{row["检查项"]}</td>'
            f'<td style="border:1px solid #ddd;padding:8px;">{row["标书要求"]}</td>'
            f'<td style="border:1px solid #ddd;padding:8px;">{row["公司情况"]}</td>'
            f'<td style="border:1px solid #ddd;padding:8px;font-weight:700;color:{color};">{row["结果"]}</td>'
            f'<td style="border:1px solid #ddd;padding:8px;">{row["风险提示"]}</td>'
            "</tr>"
        )

    if not html.startswith("<table"):
        html = "<table>" + html
    if not html.endswith("</table>"):
        html += "</table>"

    st.markdown(html, unsafe_allow_html=True)

# ========== 核心字段表格 ==========
def render_core_fields_table(core: dict[str, Any]) -> None:
    """渲染标书核心要求一览表"""
    def format_value(value: Any) -> str:
        if isinstance(value, list):
            return "\n".join([f"- {item}" for item in value]) if value else "未提取到"
        if value is None or str(value).strip() == "":
            return "未提取到"
        return str(value)

    rows = [
        {
            "关键信息": "项目名称",
            "提取结果": format_value(core.get("项目名称")),
            "状态": "✅ 已提取" if core.get("项目名称") else "⚠️ 待人工确认",
        },
        {
            "关键信息": "注册资本要求",
            "提取结果": format_value(core.get("注册资本要求")),
            "状态": "✅ 已提取" if core.get("注册资本要求") else "⚠️ 待人工确认",
        },
        {
            "关键信息": "必须具备的资质证书",
            "提取结果": format_value(core.get("必须具备的资质证书")),
            "状态": "✅ 已提取" if core.get("必须具备的资质证书") else "⚠️ 待人工确认",
        },
        {
            "关键信息": "投标截止时间",
            "提取结果": format_value(core.get("投标截止时间")),
            "状态": "✅ 已提取" if core.get("投标截止时间") else "⚠️ 待人工确认",
        },
    ]

    st.markdown("### 投标要求一览表")
    st.caption('说明：状态为"待人工确认"的字段建议回看原文二次核对。')
    st.table(rows)