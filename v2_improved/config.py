# config.py
# 这个文件负责：所有配置项、页面设置、CSS样式
# 改API地址、改模型名称、改超时时间、改页面标题，都来这里

import streamlit as st

# ========== 页面配置 ==========
def setup_page():
    """设置页面标题、图标、布局"""
    st.set_page_config(
        page_title="投标文件合规预审助手",  # ← 想改标题？改这里
        page_icon="📄",                    # ← 想改图标？改这里
        layout="centered"
    )

# ========== 打印样式 ==========
PRINT_CSS = """
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
"""

def inject_print_css():
    """注入打印样式"""
    st.markdown(PRINT_CSS, unsafe_allow_html=True)

# ========== AI配置 ==========
DEEPSEEK_BASE_URL = "https://api.deepseek.com"  # ← 换API地址？改这里
DEEPSEEK_MODEL = "deepseek-chat"                # ← 换模型？改这里
LLM_TIMEOUT_SECONDS = 60                        # ← 改超时时间？改这里

# ========== 状态初始化 ==========
def init_session_state():
    """初始化所有session_state变量"""
    defaults = {
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
        "bidding_stage": "📄 我已经有标书文件了，需要分析",
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)

def clear_cached_analysis():
    """清空缓存（上传新文件时调用），保留阶段选择和已完成的分析结果"""
    st.session_state["last_full_text"] = None
    st.session_state["company_full_text"] = None
    st.session_state["last_core"] = None
    st.session_state["company_profile"] = None
    st.session_state["last_risk_rows"] = None
    st.session_state["risk_results"] = None
    st.session_state["last_advice"] = None
    st.session_state["hidden_risks"] = None
    st.session_state["analysis_ready"] = False
    st.session_state["_file_unlocked"] = False
    # 注意：不重置 bidding_stage、all_results、company_files
    