# ui_components.py
# 这个文件负责：侧边栏、打印功能等界面组件
# 想改打印报告的样式？改这里的HTML

import streamlit as st
import streamlit.components.v1 as components
from html import escape
from io import BytesIO
from xhtml2pdf import pisa
from report_builder import build_advice


def _get_current_company_data():
    """获取当前应该打印的公司数据"""
    all_results = st.session_state.get("all_results", [])
    
    if not all_results:
        # 旧版兼容：无多公司数据，用旧字段
        return {
            "risk_rows": st.session_state.get("last_risk_rows", []),
            "advice": st.session_state.get("last_advice", ""),
            "company_name": st.session_state.get("company_file_name", "未知公司")
        }
    
    # 获取当前选中的公司名
    selected = st.session_state.get("selected_company", all_results[0]["name"])
    for r in all_results:
        if r["name"] == selected:
            return {
                "risk_rows": r["risk_rows"],
                "advice": build_advice(r["compare_result"]),
                "company_name": r["name"]
            }
    
    # 兜底：返回第一家
    return {
        "risk_rows": all_results[0]["risk_rows"],
        "advice": build_advice(all_results[0]["compare_result"]),
        "company_name": all_results[0]["name"]
    }


def generate_pdf_report(
    core: dict, risk_rows: list[dict], advice: str, hidden_risks: list[str]
) -> bytes:
    """生成PDF报告（用于下载）"""
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
        @page {{ size: A4; margin: 24pt; }}
        body {{ font-family: STSong-Light; font-size: 11pt; line-height: 1.5; color: #222; }}
        h1 {{ font-size: 22pt; font-weight: bold; margin: 0 0 18pt 0; }}
        h2 {{ font-size: 15pt; font-weight: bold; margin: 18pt 0 8pt 0; }}
        table {{ width: 100%; border-collapse: collapse; margin: 10pt 0 14pt 0; }}
        th {{ background: #f0f3f8; border: 1px solid #c7ced9; padding: 8px 6px; }}
        td {{ border: 1px solid #c7ced9; padding: 8px 6px; }}
        .ok {{ color: #2e7d32; font-weight: bold; }}
        .warn {{ color: #d32f2f; font-weight: bold; }}
      </style>
    </head>
    <body>
      <h1>投标合规风险评估报告</h1>
      <h2>一、项目概况</h2>
      <p><b>项目名称：</b>{escape(str(core.get("项目名称") or "未提取到"))}</p>
      <p><b>投标截止时间：</b>{escape(str(core.get("投标截止时间") or "未提取到"))}</p>
      <h2>二、达标对比</h2>
      <table>{table_rows_html}</table>
      <h2>三、建议话术</h2>
      <p>{escape(advice or "暂无建议")}</p>
      <h2>四、隐藏风险扫描</h2>
      <ul>{hidden_risks_html}</ul>
    </body>
    </html>
    """

    buffer = BytesIO()
    pisa_status = pisa.CreatePDF(report_html, dest=buffer, encoding="utf-8")
    if pisa_status.err:
        raise RuntimeError("PDF 生成失败")
    return buffer.getvalue()


def show_print_report():
    """在新窗口显示可打印的报告——自动打印当前选中的公司"""
    
    company_data = _get_current_company_data()
    risk_rows = company_data["risk_rows"]
    advice = company_data["advice"]
    company_name = company_data["company_name"]
    
    if not risk_rows:
        st.warning("请先完成文件比对，再打印报告。")
        return
    
    # 生成表格行
    table_rows = ""
    for row in risk_rows:
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
    
    risks_list = ""
    hidden_items = st.session_state.get("hidden_risks", [])
    if hidden_items:
        for r in hidden_items:
            risks_list += f"<li>{escape(r)}</li>"
    else:
        risks_list = "<li>未发现明显隐藏风险</li>"
    
    print_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>投标合规风险评估报告 - {escape(company_name)}</title>
        <style>
            body {{ font-family: 'Microsoft YaHei', Arial, sans-serif; padding: 30px; max-width: 1200px; margin: 0 auto; }}
            h1 {{ color: #2c3e50; border-bottom: 3px solid #3498db; padding-bottom: 10px; }}
            h2 {{ color: #34495e; margin-top: 30px; border-left: 4px solid #3498db; padding-left: 15px; }}
            table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
            th {{ background: #3498db; color: white; padding: 12px; text-align: left; }}
            td {{ border: 1px solid #ddd; padding: 10px; }}
            .info-box {{ background: #ecf0f1; padding: 15px; border-radius: 8px; margin: 15px 0; }}
            .btn {{ background: #3498db; color: white; border: none; padding: 12px 24px; border-radius: 6px; cursor: pointer; }}
            .btn:hover {{ background: #2980b9; }}
            @media print {{ .no-print {{ display: none !important; }} }}
        </style>
    </head>
    <body>
        <div class="no-print" style="margin-bottom:20px; display: flex; gap: 15px; align-items: center;">
            <button class="btn" onclick="window.print()" style="margin: 0;">🖨️ 立即打印报告</button>
            <button class="btn" onclick="this.closest('.no-print').parentElement.style.display='none'" style="background:#95a5a6; margin: 0;">✕ 收起报告</button>
            <span style="color: #888; font-size: 13px;">💡 打印后点击「收起报告」回到分析页面</span>
        </div>
        <h1>📋 投标合规风险评估报告</h1>
        <div class="info-box">
            <p><strong>公司名称：</strong>{escape(company_name)}</p>
            <p><strong>项目名称：</strong>{escape(str(st.session_state.get("last_core", {}).get("项目名称", "未提取到")))}</p>
            <p><strong>投标截止时间：</strong>{escape(str(st.session_state.get("last_core", {}).get("投标截止时间", "未提取到")))}</p>
        </div>
        <h2>📊 企业匹配结果</h2>
        <table>{table_rows}</table>
        <h2>💬 建议</h2>
        <div class="info-box"><p>{escape(advice)}</p></div>
        <h2>⚠️ 隐藏风险扫描结果</h2>
        <ul>{risks_list}</ul>
    </body>
    </html>
    """
    
    components.html(print_html, height=800, scrolling=True)