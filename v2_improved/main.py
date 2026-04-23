# main.py - 极简版，只保留核心功能
# 这是主入口！运行这个文件启动程序
# 所有功能在这里串联起来

import os
import traceback
import streamlit as st

# ========== 磁盘缓存工具 ==========
import hashlib
import json
from pathlib import Path

# ========== 环境变量读取env文件 ==========
from dotenv import load_dotenv
load_dotenv()

from config import (
    setup_page, inject_print_css, init_session_state, clear_cached_analysis,
    DEEPSEEK_BASE_URL, DEEPSEEK_MODEL, LLM_TIMEOUT_SECONDS
)
from pdf_utils import extract_pdf_text
from tender_extractor import extract_core_fields_with_ai, fallback_extract_core_fields
from company_extractor import extract_company_profile_with_ai, fallback_extract_company_profile
from comparator import compare_with_company_profile
from risk_scanner import scan_hidden_risks_with_ai
from report_builder import (
    build_advice, build_risk_rows, render_risk_table, render_core_fields_table
)
from ui_components import show_print_report

# ========== 页面初始化 ==========
setup_page()
inject_print_css()
init_session_state()

# ========== 标题 ==========
st.title("投标文件合规预审助手（双文件自动比对）")

# ========== 侧边栏 ==========
with st.sidebar:
    hidden_risk_clicked = st.button("🔍 一键审计隐藏风险", use_container_width=True)
    if st.button("🖨️ 打开打印报告", use_container_width=True):
        show_print_report()

# ========== API配置 ==========
with st.expander("AI 配置（DeepSeek API）", expanded=False):
    #env_user_key = ""  # 强制降级测试禁用AI
    env_user_key = os.getenv("OPENAI_API_KEY", "").strip() or os.getenv("DEEPSEEK_API_KEY", "").strip()
    
    if env_user_key:
        user_key = env_user_key
        st.success("已从系统环境变量读取 API Key。")
    else:
        user_key = ""
        st.warning("🔧 降级测试模式：不会调用AI")
    
    st.text_input("模型名称", value=DEEPSEEK_MODEL, disabled=True)
    st.text_input("API Base URL", value=DEEPSEEK_BASE_URL, disabled=True)
    st.text_input("请求超时(秒)", value=str(LLM_TIMEOUT_SECONDS), disabled=True)

# ========== 文件上传 ==========
uploaded_tender = st.file_uploader(
    "📄 上传招标文件（PDF）", type=["pdf"], accept_multiple_files=False, key="upload_tender"
)
uploaded_company = st.file_uploader(
    "📄 上传公司资质证明（PDF）", type=["pdf"], accept_multiple_files=False, key="upload_company"
)

# ========== 简单磁盘缓存 ==========
CACHE_DIR = Path("./cache")
CACHE_DIR.mkdir(exist_ok=True)

def get_cache(file_bytes: bytes, cache_name: str):
    """读缓存"""
    file_hash = hashlib.md5(file_bytes).hexdigest()
    cache_file = CACHE_DIR / f"{cache_name}_{file_hash}.json"
    if cache_file.exists():
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return None

def set_cache(file_bytes: bytes, cache_name: str, data):
    """写缓存"""
    file_hash = hashlib.md5(file_bytes).hexdigest()
    cache_file = CACHE_DIR / f"{cache_name}_{file_hash}.json"
    try:
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except:
        pass

# 检测文件变化
if uploaded_tender is not None:
    tender_bytes = uploaded_tender.getvalue()
    if uploaded_tender.name != st.session_state.get("tender_file_name") or tender_bytes != st.session_state.get("tender_file_bytes"):
        st.session_state["tender_file_name"] = uploaded_tender.name
        st.session_state["tender_file_bytes"] = tender_bytes
        clear_cached_analysis()

if uploaded_company is not None:
    company_bytes = uploaded_company.getvalue()
    if uploaded_company.name != st.session_state.get("company_file_name") or company_bytes != st.session_state.get("company_file_bytes"):
        st.session_state["company_file_name"] = uploaded_company.name
        st.session_state["company_file_bytes"] = company_bytes
        clear_cached_analysis()

# 显示状态
if st.session_state.get("tender_file_name"):
    st.info(f"📄 招标文件：{st.session_state['tender_file_name']}")
if st.session_state.get("company_file_name"):
    st.info(f"📄 公司资质：{st.session_state['company_file_name']}")

# ========== 明确的位置提示 ==========
st.caption("""
---
⚠️ **注意**：请确保文件位置正确
- 上方上传 **标书/招标文件**
- 下方上传 **公司营业执照/资质证明**

如果放反了，AI分析结果会出错。
""")

# ========== 开始比对按钮 ==========
run_compare = st.button(
    "🚀 开始双文件智能比对",
    disabled=not (st.session_state.get("tender_file_bytes") and st.session_state.get("company_file_bytes")),
    use_container_width=True
)

if run_compare:
    try:
        # 1. 解析PDF
        with st.spinner("📖 正在解析招标文件..."):
            tender_text = extract_pdf_text(st.session_state["tender_file_bytes"])
        if not tender_text.strip():
            st.error("❌ 招标文件未提取到文本，请检查是否为扫描件。")
            st.stop()

        with st.spinner("📖 正在解析公司资质文件..."):
            company_text = extract_pdf_text(st.session_state["company_file_bytes"])
        if not company_text.strip():
            st.error("❌ 公司资质文件未提取到文本，请检查是否为扫描件。")
            st.stop()

        st.session_state["last_full_text"] = tender_text
        st.session_state["company_full_text"] = company_text

        # 2. AI提取（或降级兜底）
        if user_key and user_key.strip():
            # ===== AI提取标书要求 =====
            core = get_cache(st.session_state["tender_file_bytes"], "tender_core")
            if core is None:
                with st.spinner("🤖 AI 正在分析标书要求..."):
                    core = extract_core_fields_with_ai(tender_text, user_key.strip())
                set_cache(st.session_state["tender_file_bytes"], "tender_core", core)
            else:
                st.success("⚡ 标书要求已从缓存加载")

            # ===== AI提取公司资质 =====
            company_profile = get_cache(st.session_state["company_file_bytes"], "company_profile")
            if company_profile is None:
                with st.spinner("🤖 AI 正在分析公司资质..."):
                    company_profile = extract_company_profile_with_ai(company_text, user_key.strip())
                set_cache(st.session_state["company_file_bytes"], "company_profile", company_profile)
            else:
                st.success("⚡ 公司资质已从缓存加载")
        else:
            # ===== 降级方案：用正则提取 =====
            st.warning("⚠️ 未配置 API Key，当前使用本地规则兜底提取。")
            core = fallback_extract_core_fields(tender_text)
            company_profile = fallback_extract_company_profile(company_text)

        # 3. 比较
        compare_result = compare_with_company_profile(core, company_profile)
        risk_rows = build_risk_rows(core, compare_result)
        advice_text = build_advice(compare_result)

        # 4. 保存结果
        st.session_state["last_core"] = core
        st.session_state["company_profile"] = company_profile
        st.session_state["last_risk_rows"] = risk_rows
        st.session_state["risk_results"] = risk_rows
        st.session_state["last_advice"] = advice_text
        st.session_state["analysis_ready"] = True

        st.success("🎉 分析完成！")
            
    except Exception as exc:
        st.error(f"❌ 分析失败：{type(exc).__name__}: {exc}")
        with st.expander("详细报错信息"):
            st.code(traceback.format_exc())

# ========== 展示结果 ==========
if st.session_state.get("analysis_ready"):
    st.divider()
    
    if st.session_state.get("last_core"):
        with st.expander("📋 标书核心要求", expanded=False):
            st.json(st.session_state["last_core"])
            render_core_fields_table(st.session_state["last_core"])

    if st.session_state.get("company_profile"):
        with st.expander("🏢 公司资质信息", expanded=False):
            st.json(st.session_state["company_profile"])

    if st.session_state.get("risk_results"):
        st.markdown("### 📊 企业匹配结果")
        render_risk_table(st.session_state["risk_results"])
        st.markdown("### 💬 建议")
        st.info(st.session_state.get("last_advice", "暂无建议"))

# ========== 隐藏风险审计 ==========
if hidden_risk_clicked:
    if not st.session_state.get("last_full_text"):
        st.warning("请先完成双文件比对")
    elif not user_key.strip():
        st.warning("请先填写 API Key")
    else:
        cache_data = get_cache(st.session_state["tender_file_bytes"], "hidden_risks")
        if cache_data is None:
            try:
                with st.spinner("🔍 AI 正在扫描隐藏风险..."):
                    risks = scan_hidden_risks_with_ai(st.session_state["last_full_text"], user_key.strip())
                set_cache(st.session_state["tender_file_bytes"], "hidden_risks", {"risks": risks})
                st.session_state["hidden_risks"] = risks
            except Exception as exc:
                st.error(f"扫描失败：{exc}")
                st.session_state["hidden_risks"] = []
        else:
            st.success("✅ 隐藏风险已从缓存加载")
            st.session_state["hidden_risks"] = cache_data.get("risks", [])
        st.rerun()

if st.session_state.get("hidden_risks") is not None:
    st.markdown("### ⚠️ 隐藏风险扫描结果")
    if st.session_state["hidden_risks"]:
        for i, risk in enumerate(st.session_state["hidden_risks"], 1):
            st.warning(f"{i}. {risk}")
    else:
        st.success("未发现明显风险")