import json
import os
import re
import traceback
from html import escape
from io import BytesIO
from typing import Any

import streamlit as st
import streamlit.components.v1 as components
from dotenv import load_dotenv
from openai import OpenAI
from pypdf import PdfReader
from xhtml2pdf import pisa


load_dotenv()

st.set_page_config(page_title="投标文件合规预审助手", page_icon="📄", layout="centered")

st.markdown(
    """
    <style>
    @media print {
      [data-testid="stSidebar"],
      .stSidebar,
      .stButton,
      [data-testid="stToolbar"],
      [data-testid="stHeader"],
      [data-testid="stDecoration"],
      footer {
        display: none !important;
      }
      [data-testid="stAppViewContainer"] .main .block-container {
        max-width: 100% !important;
        width: 100% !important;
        padding: 0.6cm 0.8cm !important;
      }
      [data-testid="stAppViewContainer"] {
        margin: 0 !important;
      }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-chat"
LLM_TIMEOUT_SECONDS = 60


def clear_cached_analysis() -> None:
    st.session_state["last_full_text"] = None
    st.session_state["company_full_text"] = None
    st.session_state["last_core"] = None
    st.session_state["company_profile"] = None
    st.session_state["last_risk_rows"] = None
    st.session_state["risk_results"] = None
    st.session_state["last_advice"] = None
    st.session_state["hidden_risks"] = None
    st.session_state["analysis_ready"] = False


def extract_pdf_text(file_bytes: bytes) -> str:
    reader = PdfReader(BytesIO(file_bytes))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n".join(pages)


def get_qualification_snippet(full_text: str, max_chars: int = 5000) -> str:
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


def fallback_extract(snippet: str) -> list[dict[str, str]]:
    rules: list[tuple[str, str]] = [
        ("注册资本", r"注册资本.{0,40}"),
        ("资质证书", r"(资质证书|资质等级).{0,40}"),
        ("营业执照", r"营业执照.{0,40}"),
        ("安全生产许可证", r"安全生产许可证.{0,40}"),
        ("业绩要求", r"(类似项目业绩|业绩要求).{0,50}"),
    ]
    items: list[dict[str, str]] = []
    for name, pattern in rules:
        m = re.search(pattern, snippet)
        if m:
            items.append(
                {
                    "要求项": name,
                    "具体要求": m.group(0).strip(),
                    "建议证明材料": "请人工复核原文并补充证明材料",
                }
            )
    return items


def extract_with_ai(snippet: str, api_key: str) -> list[dict[str, Any]]:
    client = OpenAI(
        api_key=api_key,
        base_url=DEEPSEEK_BASE_URL,
        timeout=LLM_TIMEOUT_SECONDS,
    )
    prompt = f"""
你是招投标合规审查助手。请从下面文本中提取"投标人资格要求"。
请只输出 JSON 数组，每个元素包含：
- 要求项
- 具体要求
- 建议证明材料

文本如下：
{snippet}
"""
    response = client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        temperature=0,
        messages=[
            {"role": "system", "content": "你只输出合法 JSON，不要输出任何额外文字。"},
            {"role": "user", "content": prompt},
        ],
    )
    content = response.choices[0].message.content or "[]"
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        arr_match = re.search(r"\[.*\]", content, flags=re.S)
        if arr_match:
            return json.loads(arr_match.group(0))
        raise


def fallback_extract_core_fields(raw_text: str) -> dict[str, Any]:
    def pick(pattern: str) -> str | None:
        m = re.search(pattern, raw_text, flags=re.I)
        return m.group(1).strip() if m else None

    project_name = pick(r"(?:项目名称|项目名)\s*[:：]\s*([^\n\r]+)")
    capital_requirement = pick(r"(?:注册资本(?:金)?(?:要求)?)[^。\n\r]{0,50}")
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


def extract_core_fields_with_ai(raw_text: str, api_key: str) -> dict[str, Any]:
    """
    从招标文件原始文本中提取核心字段并返回标准 JSON 字典。
    返回字段：
    - 项目名称
    - 注册资本要求
    - 必须具备的资质证书（数组）
    - 投标截止时间
    """
    client = OpenAI(
        api_key=api_key,
        base_url=DEEPSEEK_BASE_URL,
        timeout=LLM_TIMEOUT_SECONDS,
    )
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


def render_core_fields_table(core: dict[str, Any]) -> None:
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


def parse_capital_to_wan(text: str | None) -> float | None:
    """
    将"注册资本"文本转换为"万元"单位。
    示例：
    - 500万 -> 500
    - 0.5亿 -> 5000
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
    parts = re.split(r"[,\n;；、，]+", certs_text)
    return [p.strip() for p in parts if p.strip()]


def extract_company_profile_with_ai(raw_text: str, api_key: str) -> dict[str, Any]:
    client = OpenAI(
        api_key=api_key,
        base_url=DEEPSEEK_BASE_URL,
        timeout=LLM_TIMEOUT_SECONDS,
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


def fallback_extract_company_profile(raw_text: str) -> dict[str, Any]:
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


def compare_with_company_profile(core: dict[str, Any], company_profile: dict[str, Any]) -> dict[str, Any]:
    required_capital_text = core.get("注册资本要求")
    required_capital_wan = parse_capital_to_wan(required_capital_text)
    company_capital_text = company_profile.get("公司注册资本")
    company_capital_wan = parse_capital_to_wan(company_capital_text)

    required_certs = core.get("必须具备的资质证书", [])
    if not isinstance(required_certs, list):
        required_certs = []
    required_certs = [str(c).strip() for c in required_certs if str(c).strip()]

    company_certs_raw = company_profile.get("持有的证书列表", [])
    if isinstance(company_certs_raw, list):
        company_certs = [str(c).strip() for c in company_certs_raw if str(c).strip()]
    else:
        company_certs = normalize_certs(str(company_certs_raw))
    missing_certs: list[str] = []
    for req in required_certs:
        if not any(req in own or own in req for own in company_certs):
            missing_certs.append(req)

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


def build_advice(compare_result: dict[str, Any]) -> str:
    messages: list[str] = []
    if compare_result["required_capital_wan"] is not None and compare_result["company_capital_wan"] is None:
        messages.append("资质文件中未体现注册资本，建议补充营业执照或工商信息页后再决策。")
    elif compare_result["capital_not_met"]:
        messages.append("由于注册资本不足，建议联合投标或放弃本项目。")
    if compare_result["missing_certs"] and not compare_result["company_certs"]:
        messages.append("资质文件中未体现证书信息，建议补传资质附件后再评估是否投标。")
    elif compare_result["missing_certs"]:
        certs = "、".join(compare_result["missing_certs"])
        messages.append(f"资质证书存在缺失（{certs}），建议补证或寻找联合体伙伴。")
    if not messages:
        messages.append("关键门槛基本满足，建议继续核验业绩条款、付款条款和违约责任条款。")
    return " ".join(messages)


def build_risk_rows(core: dict[str, Any], compare_result: dict[str, Any]) -> list[dict[str, str]]:
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

    cert_gap = "、".join(compare_result["missing_certs"]) if compare_result["missing_certs"] else "无"
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


def render_risk_table(risk_rows: list[dict[str, str]]) -> None:
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


def scan_hidden_risks_with_ai(raw_text: str, api_key: str) -> list[str]:
    client = OpenAI(
        api_key=api_key,
        base_url=DEEPSEEK_BASE_URL,
        timeout=LLM_TIMEOUT_SECONDS,
    )
    prompt = f"""
你是投标风险审计助手。请扫描以下招标文件全文，找出表格字段之外的隐藏风险：
- 霸王条款
- 关键扣分项
- 不合理违约责任
- 付款条件苛刻项
- 资质或人员隐含限制

请仅输出 JSON：{{"risks":["...","..."]}}

文本：
{raw_text[:20000]}
"""
    response = client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": "你只返回合法 JSON。"},
            {"role": "user", "content": prompt},
        ],
    )
    content = response.choices[0].message.content or "{}"
    data = json.loads(content)
    risks = data.get("risks", [])
    if not isinstance(risks, list):
        return []
    return [str(r).strip() for r in risks if str(r).strip()]


def generate_pdf_report(
    core: dict[str, Any], risk_rows: list[dict[str, str]], advice: str, hidden_risks: list[str]
) -> bytes:
    table_rows_html = ""
    for row in risk_rows:
        result = row.get("结果", "")
        result_color = "#d32f2f" if "✖" in result else "#2e7d32"
        table_rows_html += f"""
        <tr>
          <td>{escape(row.get("检查项", ""))}</td>
          <td>{escape(row.get("标书要求", ""))}</td>
          <td>{escape(row.get("公司情况", ""))}</td>
          <td style="font-weight:700;color:{result_color};">{escape(result)}</td>
          <td>{escape(row.get("风险提示", ""))}</td>
        </tr>
        """

    hidden_risks_html = ""
    if hidden_risks:
        for idx, risk in enumerate(hidden_risks, start=1):
            hidden_risks_html += f"<li>{escape(f'{idx}. {risk}')}</li>"
    else:
        hidden_risks_html = "<li>未扫描到明显隐藏风险。</li>"

    report_html = f"""
    <html>
    <head>
      <meta charset="utf-8" />
      <style>
        @page {{
          size: A4;
          margin: 24pt;
        }}
        body {{
          font-family: STSong-Light;
          font-size: 11pt;
          line-height: 1.5;
          color: #222;
        }}
        h1 {{
          font-size: 22pt;
          font-weight: bold;
          margin: 0 0 18pt 0;
        }}
        h2 {{
          font-size: 15pt;
          font-weight: bold;
          margin: 18pt 0 8pt 0;
        }}
        p {{
          margin: 0 0 8pt 0;
        }}
        table {{
          width: 100%;
          border-collapse: collapse;
          margin: 10pt 0 14pt 0;
        }}
        th {{
          background: #f0f3f8;
          border: 1px solid #c7ced9;
          padding: 8px 6px;
          font-size: 10.5pt;
          text-align: left;
        }}
        td {{
          border: 1px solid #c7ced9;
          padding: 8px 6px;
          vertical-align: top;
          font-size: 10.5pt;
        }}
        .ok {{
          color: #2e7d32;
          font-weight: bold;
        }}
        .warn {{
          color: #d32f2f;
          font-weight: bold;
        }}
        ul {{
          margin: 0;
          padding-left: 18pt;
        }}
        .section {{
          margin-bottom: 8pt;
        }}
      </style>
    </head>
    <body>
      <h1>投标合规风险评估报告</h1>

      <h2>一、项目概况</h2>
      <p class="section"><b>项目名称：</b>{escape(str(core.get("项目名称") or "未提取到"))}</p>
      <p class="section"><b>投标截止时间：</b>{escape(str(core.get("投标截止时间") or "未提取到"))}</p>

      <h2>二、达标对比</h2>
      <table>
        <tr>
          <th>检查项</th>
          <th>标书要求</th>
          <th>公司情况</th>
          <th>结果</th>
          <th>风险提示</th>
        </tr>
        {table_rows_html}
      </table>

      <h2>三、建议话术</h2>
      <p class="section">{escape(advice or "暂无建议")}</p>

      <h2>四、隐藏风险扫描</h2>
      <ul>
        {hidden_risks_html}
      </ul>
    </body>
    </html>
    """

    buffer = BytesIO()
    pisa_status = pisa.CreatePDF(report_html, dest=buffer, encoding="utf-8")
    if pisa_status.err:
        raise RuntimeError("PDF 生成失败：HTML 转 PDF 渲染错误")
    return buffer.getvalue()


# 新增：打印报告功能（在新窗口打开）
def show_print_report():
    """在新窗口显示报告并提供打印功能"""
    if not st.session_state.get("last_core") or not st.session_state.get("last_risk_rows"):
        st.warning("请先完成文件比对，再打印报告。")
        return
    
    # 生成表格行
    table_rows = ""
    for row in st.session_state["last_risk_rows"]:
        result = row.get("结果", "")
        if "✖" in result:
            color = "#d32f2f"
        elif "⚠" in result:
            color = "#ed6c02"
        else:
            color = "#2e7d32"
        table_rows += f"""
        <tr>
            <td>{escape(row.get('检查项', ''))}</td>
            <td>{escape(row.get('标书要求', ''))}</td>
            <td>{escape(row.get('公司情况', ''))}</td>
            <td style="color:{color};font-weight:bold;">{escape(result)}</td>
            <td>{escape(row.get('风险提示', ''))}</td>
        </tr>
        """
    
    # 生成隐藏风险列表
    risks_list = ""
    hidden_items = st.session_state.get("hidden_risks", [])
    if hidden_items:
        for r in hidden_items:
            risks_list += f"<li>{escape(r)}</li>"
    else:
        risks_list = "<li>未发现明显隐藏风险</li>"
    
    # 完整的打印报告HTML
    print_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>投标合规风险评估报告</title>
        <style>
            body {{
                font-family: 'Microsoft YaHei', 'SimHei', Arial, sans-serif;
                padding: 30px;
                max-width: 1200px;
                margin: 0 auto;
                background: white;
            }}
            h1 {{
                color: #2c3e50;
                border-bottom: 3px solid #3498db;
                padding-bottom: 10px;
            }}
            h2 {{
                color: #34495e;
                margin-top: 30px;
                border-left: 4px solid #3498db;
                padding-left: 15px;
            }}
            table {{
                width: 100%;
                border-collapse: collapse;
                margin: 20px 0;
                box-shadow: 0 2px 5px rgba(0,0,0,0.1);
            }}
            th {{
                background: #3498db;
                color: white;
                padding: 12px;
                text-align: left;
                font-weight: 600;
            }}
            td {{
                border: 1px solid #ddd;
                padding: 10px;
            }}
            tr:nth-child(even) {{
                background: #f9f9f9;
            }}
            .info-box {{
                background: #ecf0f1;
                padding: 15px;
                border-radius: 8px;
                margin: 15px 0;
                border-left: 4px solid #3498db;
            }}
            .no-print {{
                margin-bottom: 20px;
            }}
            .btn {{
                background: #3498db;
                color: white;
                border: none;
                padding: 12px 24px;
                font-size: 16px;
                border-radius: 6px;
                cursor: pointer;
                margin: 10px 10px 10px 0;
                font-weight: 600;
            }}
            .btn:hover {{
                background: #2980b9;
            }}
            .btn-close {{
                background: #95a5a6;
            }}
            .btn-close:hover {{
                background: #7f8c8d;
            }}
            @media print {{
                .no-print {{
                    display: none !important;
                }}
                body {{
                    padding: 10px;
                }}
                h1 {{
                    border-bottom-color: #000;
                }}
            }}
        </style>
    </head>
    <body>
        <div class="no-print" style="margin-bottom:20px;">
            <button class="btn" onclick="window.print()">🖨️ 立即打印报告</button>
            <button class="btn btn-close" onclick="window.close()">关闭窗口</button>
            <p style="color:#7f8c8d;margin-top:10px;">💡 提示：点击"立即打印报告"按钮，然后选择打印机即可打印</p>
            <hr style="margin:20px 0;border:1px solid #eee;">
        </div>
        
        <h1>📋 投标合规风险评估报告</h1>
        
        <div class="info-box">
            <p><strong>项目名称：</strong>{escape(str(st.session_state["last_core"].get("项目名称", "未提取到")))}</p>
            <p><strong>投标截止时间：</strong>{escape(str(st.session_state["last_core"].get("投标截止时间", "未提取到")))}</p>
        </div>
        
        <h2>📊 达标对比表</h2>
        <table>
            <tr>
                <th>检查项</th>
                <th>标书要求</th>
                <th>公司情况</th>
                <th>结果</th>
                <th>风险提示</th>
            </tr>
            {table_rows}
        </table>
        
        <h2>💬 建议话术</h2>
        <div class="info-box">
            <p>{escape(st.session_state.get("last_advice", "暂无建议"))}</p>
        </div>
        
        <h2>⚠️ 隐藏风险扫描</h2>
        <ul style="line-height:1.8;">
            {risks_list}
        </ul>
        
        <div style="margin-top:40px;padding-top:20px;border-top:1px solid #ddd;color:#95a5a6;font-size:12px;">
            <p>报告生成时间：{escape(str(st.session_state.get("_report_time", "")))}</p>
        </div>
    </body>
    </html>
    """
    
    # 在新窗口中显示
    components.html(print_html, height=800, scrolling=True)


st.title("投标文件合规预审助手（双文件自动比对）")

for key, value in {
    "tender_file_name": None,
    "tender_file_bytes": None,
    "company_file_name": None,
    "company_file_bytes": None,
    "last_full_text": None,
    "company_full_text": None,
    "last_core": None,
    "company_profile": None,
    "last_risk_rows": None,
    "risk_results": None,
    "last_advice": None,
    "hidden_risks": None,
    "analysis_ready": False,
}.items():
    st.session_state.setdefault(key, value)

with st.sidebar:
    hidden_risk_clicked = st.button("🔍 一键审计隐藏风险", use_container_width=True)
    
    # 修改后的打印按钮
    if st.button("🖨️ 打开打印报告", use_container_width=True):
        show_print_report()

with st.expander("AI 配置（首次使用请填写）", expanded=False):
    env_user_key = os.getenv("OPENAI_API_KEY", "").strip() or os.getenv("DEEPSEEK_API_KEY", "").strip()
    if env_user_key:
        user_key = env_user_key
        st.success("已从系统环境变量读取 API Key。")
    else:
        user_key = st.text_input("OPENAI_API_KEY", value="", type="password")
        st.caption("未检测到环境变量，请在此输入 Key 或配置 .env 文件。")
    st.text_input("模型名称", value=DEEPSEEK_MODEL, disabled=True)
    st.text_input("API Base URL", value=DEEPSEEK_BASE_URL, disabled=True)
    st.text_input("请求超时(秒)", value=str(LLM_TIMEOUT_SECONDS), disabled=True)

uploaded_tender = st.file_uploader(
    "上传招标文件（PDF）",
    type=["pdf"],
    accept_multiple_files=False,
    key="upload_tender",
)
uploaded_company = st.file_uploader(
    "上传公司资质证明（PDF）",
    type=["pdf"],
    accept_multiple_files=False,
    key="upload_company",
)

if uploaded_tender is not None:
    tender_bytes = uploaded_tender.getvalue()
    if uploaded_tender.name != st.session_state["tender_file_name"] or tender_bytes != st.session_state["tender_file_bytes"]:
        st.session_state["tender_file_name"] = uploaded_tender.name
        st.session_state["tender_file_bytes"] = tender_bytes
        clear_cached_analysis()

if uploaded_company is not None:
    company_bytes = uploaded_company.getvalue()
    if uploaded_company.name != st.session_state["company_file_name"] or company_bytes != st.session_state["company_file_bytes"]:
        st.session_state["company_file_name"] = uploaded_company.name
        st.session_state["company_file_bytes"] = company_bytes
        clear_cached_analysis()

if st.session_state["tender_file_name"]:
    st.success(f"招标文件已缓存：`{st.session_state['tender_file_name']}`")
if st.session_state["company_file_name"]:
    st.success(f"公司资质文件已缓存：`{st.session_state['company_file_name']}`")

run_compare = st.button(
    "开始双文件智能比对",
    disabled=not (st.session_state["tender_file_bytes"] and st.session_state["company_file_bytes"]),
)

if run_compare:
    try:
        with st.spinner("正在解析招标文件..."):
            tender_text = extract_pdf_text(st.session_state["tender_file_bytes"])
        if not tender_text.strip():
            st.error("招标文件未提取到文本，请检查是否为扫描件。")
        else:
            st.session_state["last_full_text"] = tender_text

        with st.spinner("正在解析公司资质文件..."):
            company_text = extract_pdf_text(st.session_state["company_file_bytes"])
        if not company_text.strip():
            st.error("公司资质文件未提取到文本，请检查是否为扫描件。")
        else:
            st.session_state["company_full_text"] = company_text

        if st.session_state["last_full_text"] and st.session_state["company_full_text"]:
            if user_key.strip():
                with st.spinner("AI 正在提取标书要求..."):
                    core = extract_core_fields_with_ai(st.session_state["last_full_text"], user_key.strip())
                with st.spinner("AI 正在提取公司资质信息..."):
                    company_profile = extract_company_profile_with_ai(st.session_state["company_full_text"], user_key.strip())
            else:
                core = fallback_extract_core_fields(st.session_state["last_full_text"])
                company_profile = fallback_extract_company_profile(st.session_state["company_full_text"])
                st.warning("未配置 API Key，当前使用本地规则兜底提取。")

            compare_result = compare_with_company_profile(core, company_profile)
            risk_rows = build_risk_rows(core, compare_result)
            advice_text = build_advice(compare_result)

            st.session_state["last_core"] = core
            st.session_state["company_profile"] = company_profile
            st.session_state["last_risk_rows"] = risk_rows
            st.session_state["risk_results"] = risk_rows
            st.session_state["last_advice"] = advice_text
            st.session_state["analysis_ready"] = True
            st.session_state["_report_time"] = str(st.session_state.get("_report_time", ""))
    except Exception as exc:
        st.error(f"提取失败：{type(exc).__name__}: {exc}")
        with st.expander("详细报错信息", expanded=False):
            st.code(traceback.format_exc())

if st.session_state.get("analysis_ready") and st.session_state.get("last_core"):
    st.subheader("标书核心要求（JSON）")
    st.json(st.session_state["last_core"], expanded=True)
    render_core_fields_table(st.session_state["last_core"])

if st.session_state.get("analysis_ready") and st.session_state.get("company_profile"):
    st.subheader("公司资质提取结果（JSON）")
    st.json(st.session_state["company_profile"], expanded=True)

if st.session_state.risk_results is not None:
    st.markdown("### 企业匹配结果")
    render_risk_table(st.session_state.risk_results)
    st.markdown("### 建议话术")
    st.info(st.session_state.get("last_advice") or "暂无建议")

if hidden_risk_clicked:
    full_text = st.session_state.get("last_full_text")
    if not full_text:
        st.warning("请先完成双文件比对，再执行隐藏风险审计。")
    elif not user_key.strip():
        st.warning("请先填写 API Key，再执行隐藏风险审计。")
    else:
        try:
            with st.spinner("AI 正在扫描隐藏风险..."):
                hidden_risks = scan_hidden_risks_with_ai(full_text, user_key.strip())
            st.session_state["hidden_risks"] = hidden_risks
        except Exception as exc:
            st.error(f"隐藏风险审计失败：{type(exc).__name__}: {exc}")
            with st.expander("详细报错信息", expanded=False):
                st.code(traceback.format_exc())

if st.session_state.get("hidden_risks") is not None:
    st.markdown("### 隐藏风险审计结果")
    hidden_items = st.session_state.get("hidden_risks", [])
    if hidden_items:
        for i, risk in enumerate(hidden_items, start=1):
            st.warning(f"{i}. {risk}")
    else:
        st.success("未发现明显霸王条款或关键扣分项。")

