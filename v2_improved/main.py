# main.py
# 这是主入口！运行这个文件启动程序
# 所有功能在这里串联起来

import os
import json
import traceback
import streamlit as st
from logger_config import logger



# ========== 磁盘缓存工具 ==========
import hashlib
from pathlib import Path
from pdf_utils import extract_pdf_text
        

# ========== 环境变量读取env文件 ==========
from dotenv import load_dotenv
load_dotenv()

from config import (
    setup_page, inject_print_css, init_session_state, clear_cached_analysis,
    DEEPSEEK_BASE_URL, DEEPSEEK_MODEL, LLM_TIMEOUT_SECONDS
)
from pdf_utils import extract_pdf_text
from tender_extractor import (
    extract_core_fields_structured,
    fallback_extract_core_fields
)
from company_extractor import (
    extract_company_profile_structured,
    fallback_extract_company_profile
)
from comparator import compare_with_company_profile
from risk_scanner import scan_hidden_risks_streaming, parse_risk_streaming_result
from report_builder import (
    build_advice, build_risk_rows, render_risk_table, render_core_fields_table
)
from ui_components import show_print_report

def _save_agent_conversation():
    """保存当前 Agent 对话到数据库"""
    from history_db import save_conversation
    agent_state = st.session_state.get("agent_state", {})
    core = agent_state.get("core") or {}
    tender_name = core.get("项目名称", "未命名")
    msgs = agent_state.get("messages", [])
    if msgs:
        seen = set()
        unique = []
        for m in msgs:
            c = m.get("content", "").strip()
            if c and c not in seen:
                seen.add(c)
                unique.append(m)
        if unique:
            save_conversation(tender_name, unique)
            logger.info(f"已保存对话：{tender_name}，共 {len(unique)} 条消息")


# ========== 页面初始化 ==========
setup_page()
inject_print_css()
init_session_state()

if "hidden_risks" not in st.session_state:
    st.session_state["hidden_risks"] = None

# ========== 标题 ==========
st.title("招投标全流程助手")


# ========== 侧边栏 ==========
with st.sidebar:
    # --- 功能按钮 ---
    hidden_risk_clicked = st.button("🔍 一键审计隐藏风险", use_container_width=True)
    if st.button("🖨️ 打开打印报告", use_container_width=True):
        show_print_report()
    st.divider()
    st.markdown("### 📜 历史记录")
    if st.button("查看历史记录", use_container_width=True):
        st.session_state["show_history_all"] = True
    st.divider()
    st.markdown("### 🤖 Agent 模式")
    if st.button("启动 Agent 分析", use_container_width=True):
        st.session_state["agent_mode"] = True

    # --- 文件预处理状态 ---
    st.divider()
    st.markdown("### 🔧 文件预处理")

    mode = st.session_state.get("preprocessing_mode", "unknown")
    message = st.session_state.get("_preprocess_message", "")
    tender_bytes = st.session_state.get("tender_file_bytes", b"")

    if mode == "direct":
        st.success(f"📄 标书：{message}")
    elif mode == "ocr":
        st.warning(f"📄 标书：{message}")
        if tender_bytes:
            if st.button("🔍 启动 OCR 识别", key="ocr_tender"):
                with st.spinner("📷 正在进行 OCR 识别，请耐心等待..."):
                    try:
                        is_pdf_file = tender_bytes[:4] == b'%PDF'
                        if is_pdf_file:
                            from ocr_utils import ocr_pdf
                            ocr_text = ocr_pdf(tender_bytes)
                        else:
                            from ocr_utils import ocr_image
                            ocr_text = ocr_image(tender_bytes)

                        if ocr_text and ocr_text.strip():
                            ocr_bytes = ocr_text.encode('utf-8')
                            st.session_state["tender_file_bytes"] = ocr_bytes
                            st.session_state["_ocr_done_flag"] = True
                            st.session_state["preprocessing_mode"] = "direct"
                            st.session_state["_preprocess_message"] = f"✅ OCR 识别完成（{len(ocr_text)} 字符）"
                            st.session_state["_file_unlocked"] = True
                            st.session_state["_last_text_extraction_key"] = "__ocr_done__"
                            st.rerun()
                        else:
                            st.session_state["_preprocess_message"] = "❌ OCR 未能识别出文字"
                            st.rerun()
                    except Exception as e:
                        st.session_state["_preprocess_message"] = f"OCR 失败: {str(e)[:100]}"
                        st.rerun()

    elif mode == "decrypt":
        st.warning(f"📄 标书：{message}")
        if st.button("🔓 尝试自动解锁", key="auto_unlock_tender"):
            with st.spinner("正在尝试自动解锁..."):
                try:
                    from pdf_unlocker import attempt_auto_unlock
                    unlocked_bytes, method = attempt_auto_unlock(tender_bytes)
                    if method in ['direct', 'qpdf']:
                        st.success("✅ 文件已解锁，可正常读取")
                        st.session_state["preprocessing_mode"] = "direct"
                        st.session_state["tender_file_bytes"] = unlocked_bytes
                        st.session_state["_last_text_extraction_key"] = "__unlocked__"
                        st.rerun()
                    else:
                        st.warning("⚠️ 自动解锁失败，请手动输入密码")
                except Exception as e:
                    st.error(f"解锁失败: {str(e)[:200]}")

        password = st.text_input("🔑 请输入文件打开密码", key="file_password", type="password")
        if st.button("🔓 用密码解锁", key="pwd_unlock_tender"):
            if not password:
                st.error("❌ 请先输入密码")
            else:
                with st.spinner("正在验证密码..."):
                    try:
                        from pdf_unlocker import try_remove_password
                        unlocked_bytes = try_remove_password(tender_bytes, password)
                        st.success("✅ 密码正确，文件已解锁")
                        st.session_state["preprocessing_mode"] = "direct"
                        st.session_state["tender_file_bytes"] = unlocked_bytes
                        st.session_state["_last_text_extraction_key"] = "__unlocked__"
                        st.session_state["tender_file_name"] = st.session_state.get("tender_file_name", "")
                        st.session_state["_file_unlocked"] = True
                        st.session_state["_trigger_analysis"] = True
                        st.rerun()
                    except ValueError as e:
                        st.error(f"❌ {e}")
                    except RuntimeError as e:
                        st.error(f"❌ {e}")

    elif mode == "failed":
        st.error(f"📄 标书：{message}")
        st.info("💡 建议：请检查文件是否损坏，或尝试用其他软件打开后重新导出为PDF")
    else:
        st.caption("📄 标书：等待上传...")

    # --- 公司资质文件状态 ---
    company_files = st.session_state.get("company_files", [])
    if company_files:
        for idx, cf in enumerate(company_files):
            cf_name = cf["name"]
            cf_bytes = cf["bytes"]
            cf_size = len(cf_bytes)
            cf_detection_key = f"{cf_name}_{cf_size}"
            cf_last_key = st.session_state.get(f"_company_check_{idx}", "")

            if cf_detection_key != cf_last_key:
                try:
                    cf_header = cf_bytes[:5].decode('latin-1', errors='ignore')
                    if not cf_header.startswith('%PDF-'):
                        cf_status = "failed"
                        cf_msg = f"🏢 {cf_name}：❌ 不是有效的 PDF 文件"
                    else:
                        cf_text = extract_pdf_text(cf_bytes)
                        if not cf_text or len(cf_text.strip()) < 20:
                            cf_status = "failed"
                            cf_msg = f"🏢 {cf_name}：❌ 提取信息不足"
                        else:
                            cf_status = "direct"
                            cf_msg = f"🏢 {cf_name}：✅ 已处理（{len(cf_text.strip())}字符）"
                except Exception:
                    cf_status = "failed"
                    cf_msg = f"🏢 {cf_name}：❌ 解析失败"

                st.session_state[f"_company_status_{idx}"] = cf_status
                st.session_state[f"_company_message_{idx}"] = cf_msg
                st.session_state[f"_company_check_{idx}"] = cf_detection_key

            cf_status = st.session_state.get(f"_company_status_{idx}", "unknown")
            cf_msg = st.session_state.get(f"_company_message_{idx}", "")
            if cf_status == "direct":
                st.success(cf_msg)
            else:
                st.error(cf_msg)
    else:
        st.caption("🏢 公司资质：等待上传...")


# ========== API配置 ==========
with st.expander("AI 配置（DeepSeek API）", expanded=False):
    env_user_key = os.getenv("OPENAI_API_KEY", "").strip() or os.getenv("DEEPSEEK_API_KEY", "").strip()
    
    if env_user_key:
        user_key = env_user_key
        st.session_state["user_key"] = user_key 
        st.success("已从系统环境变量读取 API Key。")
    else:
        user_key = ""
        st.session_state["user_key"] = user_key
        st.warning("🔧 降级测试模式：不会调用AI")
    
    st.text_input("模型名称", value=DEEPSEEK_MODEL, disabled=True)
    st.text_input("API Base URL", value=DEEPSEEK_BASE_URL, disabled=True)
    st.text_input("请求超时(秒)", value=str(LLM_TIMEOUT_SECONDS), disabled=True)


# ========== 投标阶段分流 ==========
st.markdown("**您目前处在哪个阶段：**")

stage = st.radio(
    "",
    [
        "🔰 我刚看到招标公告，还没报名",
        "📝 我已经报名/确认参与，需要下载标书",
        "📦 我下载了标书文件，但打不开/格式不对",
        "📄 我已经有标书文件了，需要分析",
    ],
    key="bidding_stage"
)

# 从 tools.py 导入新增的工具函数
from tools import get_platform_guide, diagnose_file_issue

# ===== 阶段一：还没报名 =====
if stage.startswith("🔰"):
    uploaded_tender = None
    source_type = "🔗"  # 保持兼容，后续压缩包解压等逻辑依赖此变量
    
    st.info("""
    ### 🔰 投标前置准备
    
    在获取标书之前，通常需要完成以下步骤。请确认您已准备就绪：
    """)
    
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**✅ 需要准备的材料：**")
        st.markdown("- 营业执照副本（电子版）")
        st.markdown("- 法人身份证（电子版）")
        st.markdown("- 企业资质证书（电子版）")
        st.markdown("- 授权委托书（如有代理人）")
    with col2:
        st.markdown("**🔐 需要办理的工具：**")
        st.markdown("- CA数字证书（实体锁或手机CA）")
        st.markdown("- 平台供应商注册")
        st.markdown("- 投标文件制作软件")
    
    st.warning("""
    ⚠️ **请先确认您要投标的平台名称。** 不同平台有不同的注册和CA要求。
    
    如果您知道平台名称（如政采云、广联达、新点、筑龙），请告诉我，我可以提供该平台的具体操作指引。
    """)
    
    platform_query = st.text_input("💬 请输入您要投标的平台名称（如不确定可留空）", key="platform_query_stage1")
    if platform_query:
        result = get_platform_guide(platform_query)
        st.success(result)

# ===== 阶段二：已报名，需要下载标书 =====
elif stage.startswith("📝"):
    uploaded_tender = None
    source_type = "🔗"
    
    st.info("""
    ### 📝 标书文件获取
    
    您已完成报名，现在需要下载招标文件。请按以下步骤操作：
    """)
    
    st.markdown("**请先确认您使用的电子交易平台：**")
    platform_query = st.text_input("💬 输入平台名称（如政采云、广联达、新点、筑龙）", key="platform_query_stage2")
    if platform_query:
        result = get_platform_guide(platform_query)
        st.success(result)
    
    st.divider()
    st.warning("""
    ⚠️ **重要提醒：**
    - 招标文件格式通常为平台专用格式（如 .SDTF、.ZYHBZF 等），**不是通用PDF**
    - 下载后请使用平台配套的标书制作工具打开
    - 请记录下载时间，确保在投标截止时间之前
    - 如遇技术问题，建议直接拨打招标公告上的技术支持电话
    """)

# ===== 阶段三：下载了但打不开 =====
elif stage.startswith("📦"):
    uploaded_tender = None
    source_type = "📦"
    
    st.info("""
    ### 📦 文件格式诊断
    
    请描述您遇到的情况，我来帮您判断问题。
    """)
    
    file_issue = st.text_input(
        "💬 描述您的问题（如：文件后缀是什么？打开时提示什么错误？）",
        key="file_issue_query"
    )
    if file_issue:
        diagnosis = diagnose_file_issue(file_issue)
        st.success(diagnosis)
    
    st.divider()
    st.caption("常见问题：")
    st.markdown("- .SDTF / .SXSTF 格式 → 需用新点标书制作工具打开")
    st.markdown("- .ZYHBZF 格式 → 需用筑龙标书制作工具打开")
    st.markdown("- .gld / .gcf 格式 → 需用广联达GCCP软件打开")
    st.markdown("- 打开提示'需插入CA锁' → 请检查CA锁是否正确连接")
    st.markdown("- 文件有密码 → 请在上传区上传，系统可尝试自动解锁")

# ===== 阶段四：有文件，需要分析 =====
else:
    source_type = "📎"
    
    st.success("""
    ### 📄 标书分析
    
    请上传您的标书文件和公司资质文件，系统将自动进行分析。
    """)
    
    uploaded_tender = st.file_uploader(
        "📄 上传招标文件（PDF/Word/图片）",
        type=["pdf", "docx", "doc", "png", "jpg", "jpeg"],
        accept_multiple_files=False,
        key="upload_tender"
    )

# ========== 公司资质上传（始终显示，但只有阶段四才有意义） ==========
uploaded_company = st.file_uploader(
    "📄 上传公司资质证明（PDF/Word）",
    type=["pdf", "docx", "doc"],
    accept_multiple_files=True,
    key="upload_company"
)

# ========== 简单磁盘缓存 ==========
CACHE_DIR = Path("./cache")
CACHE_DIR.mkdir(exist_ok=True)

def get_cache(file_bytes: bytes, cache_name: str):
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
    # 如果文件已经解锁，不要用原始加密版本覆盖
    if not st.session_state.get("_file_unlocked", False):
        if uploaded_tender.name != st.session_state.get("tender_file_name") or tender_bytes != st.session_state.get("tender_file_bytes"):
            st.session_state["tender_file_name"] = uploaded_tender.name
            st.session_state["tender_file_bytes"] = tender_bytes
            clear_cached_analysis()
    else:
        # 文件已解锁，保持解锁后的版本不变
        pass
        
if uploaded_company:
    new_files = [{"name": f.name, "bytes": f.getvalue()} for f in uploaded_company]
    old_files = st.session_state.get("company_files", [])
    if new_files != old_files:
        st.session_state["company_files"] = new_files
        clear_cached_analysis()


# ========== 压缩包自动解压（代理机构场景） ==========
if source_type.startswith("🏢") and st.session_state.get("tender_file_bytes"):
    fname = st.session_state.get("tender_file_name", "").lower()
    tender_bytes = st.session_state.get("tender_file_bytes")
    
    if fname.endswith(('.zip', '.rar')):
        # 只处理一次，用 session_state 标记避免重复解压
        archive_key = f"archive_extracted_{fname}"
        if not st.session_state.get(archive_key, False):
            try:
                from archive_utils import extract_archive
                extracted = extract_archive(tender_bytes, fname)
                if extracted:
                    pdf_files = [k for k in extracted if k.lower().endswith('.pdf')]
                    doc_files = [k for k in extracted if k.lower().endswith(('.docx', '.doc'))]
                    all_docs = pdf_files + doc_files
                    
                    if all_docs:
                        main_file = all_docs[0]
                        st.session_state["tender_file_bytes"] = extracted[main_file]
                        st.session_state["tender_file_name"] = main_file
                        st.session_state[archive_key] = True
                        st.success(f"✅ 压缩包已解压，找到 {len(extracted)} 个文件，使用 {main_file} 作为主标书")
                        if len(extracted) > 1:
                            st.caption(f"压缩包内含：{', '.join(extracted.keys())}")
                        st.rerun()
                    else:
                        st.warning("⚠️ 压缩包内未找到 PDF 或 Word 文件，请手动上传标书")
                else:
                    st.warning("⚠️ 压缩包为空或无法解压")
            except Exception as e:
                st.error(f"解压失败: {str(e)[:200]}")




# ========== 【新增】文件预处理分流 (修正版) ==========
if st.session_state.get("tender_file_bytes"):
    tender_bytes = st.session_state["tender_file_bytes"]
    current_file_name = st.session_state.get("tender_file_name", "")

    # ===== 1. 先做一次极快的文件头检查 =====
    is_pdf = tender_bytes[:4] == b'%PDF'
    is_png = tender_bytes[:8] == b'\x89PNG\r\n\x1a\n'
    is_jpg = tender_bytes[:2] == b'\xff\xd8'

    # ===== 0. OCR/解锁完成后直接放行，跳过文件头检测 =====
    if st.session_state.get("_last_text_extraction_key") in ("__ocr_done__", "__unlocked__"):
        st.session_state["preprocessing_mode"] = "direct"
        st.session_state["_preprocess_message"] = "✅ 文件已就绪，可开始分析"
    # ===== 原来的文件头检测 =====
    elif is_png or is_jpg:
        # 图片文件，直接走 OCR
        st.session_state["preprocessing_mode"] = "ocr"
        st.session_state["_preprocess_message"] = "📷 检测到图片文件，需要 OCR 识别"
    elif not is_pdf:
        st.session_state["preprocessing_mode"] = "failed"
        st.session_state["_preprocess_message"] = f"❌ 文件格式无效，请上传 PDF 或图片文件"
    else:
        file_size = len(tender_bytes)
        detection_key = f"{current_file_name}_{file_size}"
        last_detection_key = st.session_state.get("_last_text_extraction_key", "")



        if st.session_state.get("_last_text_extraction_key") == "__ocr_done__":
            st.session_state["preprocessing_mode"] = "direct"
            st.session_state["_preprocess_message"] = f"✅ OCR 识别完成"

        if detection_key != last_detection_key:
            # 只有当文件真的变了（名或大小），才执行耗时操作
            # === 如果文件已经解锁成功，直接跳过检测 ===
            if st.session_state.get("_file_unlocked", False):
                st.session_state["preprocessing_mode"] = "direct"
                st.session_state["_preprocess_message"] = "✅ 文件已解锁，可正常读取"
                st.session_state["_last_text_extraction_key"] = detection_key
            else:
                try:
                    test_text = extract_pdf_text(tender_bytes)
                    if not test_text or len(test_text.strip()) == 0:
                        st.session_state["preprocessing_mode"] = "failed"
                        st.session_state["_preprocess_message"] = "❌ 文件无法解析：提取文本为空，可能文件已损坏或为扫描件"
                    elif len(test_text.strip()) < 50:
                        st.session_state["preprocessing_mode"] = "ocr"
                        st.session_state["_preprocess_message"] = f"⚠️ 文件文本极少（{len(test_text.strip())}字符），可能是扫描件或图片型PDF"
                    else:
                        st.session_state["preprocessing_mode"] = "direct"
                        st.session_state["_preprocess_message"] = f"✅ 文件可正常读取（{len(test_text.strip())}字符）"
                        # 更新key，防止下次rerun重复检测
                    st.session_state["_last_text_extraction_key"] = detection_key
                except Exception as e:
                    error_msg = str(e).lower()
                    if any(keyword in error_msg for keyword in ["encrypt", "password", "permission", "加密", "密码"]):
                        st.session_state["preprocessing_mode"] = "decrypt"
                        st.session_state["_preprocess_message"] = "🔒 文件已加密，请输入密码解锁"
                    else:
                        st.session_state["preprocessing_mode"] = "failed"
                        st.session_state["_preprocess_message"] = f"❌ 无法读取文件: {str(e)[:100]}"
                    st.session_state["_last_text_extraction_key"] = detection_key
        # 如果 detection_key 没变，说明是同一个文件的重复rerun。
        # 我们什么都不做，直接沿用上一次的 preprocessing_mode 和 message。
        # 所以这里不需要 else 分支。


# ========== 显示已上传文件信息 ==========
if st.session_state.get("tender_file_name"):
    st.info(f"📄 招标文件：{st.session_state['tender_file_name']}")
if st.session_state.get("company_files"):
    count = len(st.session_state["company_files"])
    names = ", ".join([f["name"] for f in st.session_state["company_files"]])
    st.info(f"📄 公司资质（{count}份）：{names}")

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
    disabled=not (
        st.session_state.get("tender_file_bytes") 
        and st.session_state.get("company_files")
        and st.session_state.get("preprocessing_mode") == "direct"
    ),
    use_container_width=True
)

# 解锁成功后自动触发分析
if st.session_state.get("_trigger_analysis", False):
    st.session_state["_trigger_analysis"] = False
    if (
        st.session_state.get("tender_file_bytes") 
        and st.session_state.get("company_files")
        and st.session_state.get("preprocessing_mode") == "direct"
    ):
        run_compare = True


if run_compare:
    
    logger.info("用户点击「开始比对」")
    try:
        with st.spinner("📖 正在解析招标文件..."):
            tender_bytes = st.session_state["tender_file_bytes"]
            if st.session_state.get("_ocr_done_flag"):
                tender_text = tender_bytes.decode('utf-8')
                st.session_state["_ocr_done_flag"] = False
            elif tender_bytes[:4] != b'%PDF':
                tender_text = tender_bytes.decode('utf-8')
            else:
                tender_text = extract_pdf_text(tender_bytes)

        if not tender_text.strip():
            st.error("❌ 招标文件未提取到文本，请检查是否为扫描件。")
            st.stop()
        logger.info(f"招标文件解析成功，文本长度: {len(tender_text)} 字符")
        st.session_state["last_full_text"] = tender_text

        if user_key and user_key.strip():
            logger.info("检测到 API Key，使用结构化 AI 提取")

            core = get_cache(st.session_state["tender_file_bytes"], "tender_core")
            if core is None:
                logger.info("标书要求缓存未命中，使用结构化 AI 提取")
                with st.spinner("🤖 AI 正在分析标书要求..."):
                    core = extract_core_fields_structured(tender_text, user_key.strip())
                set_cache(st.session_state["tender_file_bytes"], "tender_core", core)
                logger.info("标书要求提取成功，已写入缓存")
            else:
                logger.info("标书要求从磁盘缓存加载")
                st.success("⚡ 标书要求已从缓存加载")

            all_results = []
            for idx, company_file in enumerate(st.session_state["company_files"]):
                company_name = company_file["name"]
                company_bytes = company_file["bytes"]

                st.markdown(f"---")
                st.markdown(f"### 🏢 正在分析第 {idx+1}/{len(st.session_state['company_files'])} 份：{company_name}")

                company_text = extract_pdf_text(company_bytes)
                if not company_text.strip():
                    st.warning(f"⚠️ {company_name} 未提取到文本，跳过")
                    continue

                company_profile = get_cache(company_bytes, "company_profile")
                if company_profile is None:
                    logger.info(f"{company_name} 缓存未命中，使用结构化 AI 提取")
                    with st.spinner(f"🤖 AI 正在分析 {company_name}..."):
                        company_profile = extract_company_profile_structured(company_text, user_key.strip())
                    set_cache(company_bytes, "company_profile", company_profile)
                    logger.info(f"{company_name} 提取成功，已写入缓存")
                else:
                    st.success(f"⚡ {company_name} 已从缓存加载")

                compare_result = compare_with_company_profile(core, company_profile)
                risk_rows = build_risk_rows(core, compare_result)

                all_results.append({
                    "name": company_name,
                    "profile": company_profile,
                    "compare_result": compare_result,
                    "risk_rows": risk_rows
                })

                st.markdown(f"**{company_name} 对比结果：**")
                render_risk_table(risk_rows)

            if len(all_results) > 1:
                st.markdown("---")
                st.markdown("## 📊 多公司对比汇总")
                summary = []
                for r in all_results:
                    missing_count = len(r["compare_result"]["missing_certs"])
                    capital_ok = "✅" if not r["compare_result"]["capital_not_met"] else "✖"
                    summary.append({
                        "公司": r["name"],
                        "注册资本": capital_ok,
                        "缺失证书数": missing_count,
                    })
                st.table(summary)
                best = min(all_results, key=lambda r: len(r["compare_result"]["missing_certs"]))
                st.success(f"🏆 推荐选择：**{best['name']}**")

            if all_results:
                st.session_state["last_core"] = core
                st.session_state["all_results"] = all_results 
                st.session_state["company_profile"] = all_results[0]["profile"]
                st.session_state["last_risk_rows"] = all_results[0]["risk_rows"]
                st.session_state["risk_results"] = all_results[0]["risk_rows"]
                st.session_state["last_advice"] = build_advice(all_results[0]["compare_result"])
                st.session_state["analysis_ready"] = True
                logger.info("分析完成，结果已保存到 session_state")
                st.success("🎉 分析完成！")
                if st.session_state.get("hidden_risks") is None:
                    st.info("💡 点击左侧「一键审计隐藏风险」完善报告，扫描结果将自动存入历史记录。")
                from history_db import save_analysis
                tender_name = core.get("项目名称") or "未命名标书"
                best_name = min(all_results, key=lambda r: len(r["compare_result"]["missing_certs"]))["name"] if len(all_results) > 1 else all_results[0]["name"]
                save_analysis(tender_name, all_results, best_name, st.session_state.get("hidden_risks", []), core)
                logger.info(f"已保存到历史记录：{tender_name}，{len(all_results)}家公司，最优：{best_name}")

        else:
            logger.warning("API Key 为空，启用降级方案（正则提取）")
            st.warning("⚠️ 未配置 API Key，当前使用本地规则兜底提取。")
            core = fallback_extract_core_fields(tender_text)
            if not core.get("项目名称") and not core.get("注册资本要求"):
                st.info("💡 正则未能提取到关键信息，建议配置 API Key 以获得准确结果。")
            if st.session_state.get("company_files"):
                first_company = st.session_state["company_files"][0]
                company_text = extract_pdf_text(first_company["bytes"])
                company_profile = fallback_extract_company_profile(company_text)
                logger.info("降级提取完成")
                compare_result = compare_with_company_profile(core, company_profile)
                risk_rows = build_risk_rows(core, compare_result)
                st.session_state["last_core"] = core
                st.session_state["company_profile"] = company_profile
                st.session_state["last_risk_rows"] = risk_rows
                st.session_state["risk_results"] = risk_rows
                st.session_state["last_advice"] = build_advice(compare_result)
                st.session_state["analysis_ready"] = True
                st.success("🎉 分析完成！")

    except Exception as exc:
        logger.error(f"分析失败: {type(exc).__name__} - {exc}")
        st.error(f"❌ 分析失败：{type(exc).__name__}: {exc}")
        with st.expander("详细报错信息"):
            st.code(traceback.format_exc())

# ========== 展示结果 ==========
if st.session_state.get("analysis_ready"):
    logger.info("开始展示分析结果")
    st.divider()
    all_results = st.session_state.get("all_results", [])
    
    if not st.session_state.get("last_core") and all_results:
        st.session_state["last_core"] = {
            "项目名称": "历史记录",
            "注册资本要求": "",
            "必须具备的资质证书": [],
            "投标截止时间": ""
        }
    
    if len(all_results) > 1:
        company_names = [r["name"] for r in all_results]
        selected = st.selectbox("选择查看的公司", company_names, key="selected_company")
        selected_result = all_results[company_names.index(selected)]
    elif len(all_results) == 1:
        selected_result = all_results[0]
    else:
        selected_result = None
    
    if st.session_state.get("last_core"):
        with st.expander("📋 标书核心要求", expanded=False):
            st.json(st.session_state["last_core"])
            render_core_fields_table(st.session_state["last_core"])

    if selected_result:
        st.markdown(f"### 🏢 {selected_result['name']}")
        render_risk_table(selected_result["risk_rows"])
        
        
    elif st.session_state.get("risk_results"):
        st.markdown("### 📊 企业匹配结果")
        render_risk_table(st.session_state["risk_results"])
        st.markdown("### 💬 建议")
        st.info(st.session_state.get("last_advice", "暂无建议"))
        

# ========== 隐藏风险审计 ==========
if hidden_risk_clicked:
    logger.info("用户点击「隐藏风险审计」")
    if not st.session_state.get("last_full_text"):
        st.warning("请先完成双文件比对")
    elif not user_key.strip():
        st.warning("请先填写 API Key")
    else:
        cache_data = get_cache(st.session_state["tender_file_bytes"], "hidden_risks")
        if cache_data is None:
            logger.info("隐藏风险缓存未命中，使用流式 AI 扫描")
            try:
                display_placeholder = st.empty()
                full_text = ""
                for token, current_text in scan_hidden_risks_streaming(st.session_state["last_full_text"], user_key.strip()):
                    full_text = current_text
                    display_placeholder.markdown(f"### 🔍 AI 正在扫描隐藏风险...\n\n```json\n{full_text}▌\n```")
                risks = parse_risk_streaming_result(full_text)
                display_placeholder.markdown(f"### ✅ 隐藏风险扫描完成\n\n```json\n{json.dumps({'risks': risks}, ensure_ascii=False, indent=2)}\n```")
                set_cache(st.session_state["tender_file_bytes"], "hidden_risks", {"risks": risks})
                st.session_state["hidden_risks"] = risks
                from history_db import update_latest_risks
                update_latest_risks(risks)
                logger.info(f"隐藏风险扫描成功，发现 {len(risks)} 个风险项")
            except Exception as exc:
                logger.error(f"隐藏风险扫描失败: {exc}")
                st.error(f"扫描失败：{exc}")
                st.session_state["hidden_risks"] = []
        else:
            logger.info("隐藏风险从磁盘缓存加载")
            st.success("✅ 隐藏风险已从缓存加载")
            st.session_state["hidden_risks"] = cache_data.get("risks", [])
            from history_db import update_latest_risks
            update_latest_risks(st.session_state["hidden_risks"])
        st.rerun()

if st.session_state.get("hidden_risks") is not None:
    risk_count = len(st.session_state["hidden_risks"])
    logger.info(f"展示隐藏风险结果：{risk_count} 个风险项")
    st.markdown(f"### ⚠️ 隐藏风险扫描结果（基于标书，共{risk_count}项）")
    if st.session_state["hidden_risks"]:
        for i, risk in enumerate(st.session_state["hidden_risks"], 1):
            st.warning(f"{i}. {risk}")
    else:
        st.success("未发现明显风险")

# ========== Agent 模式 ==========
if st.session_state.get("agent_mode"):
    from agent import build_agent, AgentState
    
    if not st.session_state.get("user_key") and 'user_key' in dir():
        st.session_state["user_key"] = user_key
    
    if st.session_state.get("tender_file_bytes"):
        tender_text = extract_pdf_text(st.session_state["tender_file_bytes"])
        st.session_state["last_full_text"] = tender_text
    
    st.divider()
    st.markdown("## 🤖 Agent 分析模式")
    st.caption("用自然语言告诉 Agent 你想做什么，它会自动调用相应的分析功能。")
    
    agent = build_agent()
    
    if "agent_has_analyzed" not in st.session_state:
        st.session_state["agent_has_analyzed"] = False

    if "agent_state" not in st.session_state:
        tender_text = st.session_state.get("last_full_text", "")
        if not tender_text and st.session_state.get("tender_file_bytes"):
            tender_text = extract_pdf_text(st.session_state["tender_file_bytes"])
        st.session_state["agent_state"] = {
            "messages": [],
            "tender_text": tender_text,
            "company_files": [
                {"name": f["name"], "text": extract_pdf_text(f["bytes"])}
                for f in st.session_state.get("company_files", [])
            ],
            "analysis_done": False,
            "core": None,
            "all_results": [],
            "reflection_done": False,
        }
    
    seen = set()
    for msg in st.session_state["agent_state"].get("messages", []):
        content = msg.get("content", "").strip()
        if not content:
            continue
        key = content[:60]
        if key not in seen:
            seen.add(key)
            role = msg.get("role", "user")
            st.chat_message(role).write(msg["content"])
    
    user_input = st.chat_input("告诉 Agent 你想做什么...")
    if user_input:
        st.session_state["agent_state"]["messages"].append({"role": "user", "content": user_input})
        
        from tools import try_handle_with_tool
        tool_result = try_handle_with_tool(user_input, st.session_state["agent_state"].get("core", {}), st.session_state.get("user_key", ""))
        
        if tool_result:
            st.session_state["agent_state"]["messages"].append({"role": "assistant", "content": tool_result})
            # ⭐ 保存对话
            _save_agent_conversation()
            st.rerun()

        elif not st.session_state["agent_has_analyzed"]:
            if not st.session_state["agent_state"].get("tender_text"):
                if st.session_state.get("last_full_text"):
                    st.session_state["agent_state"]["tender_text"] = st.session_state["last_full_text"]
                else:
                    from agent import node_chat
                    result = node_chat(st.session_state["agent_state"])
                    st.session_state["agent_state"] = result
                    # ⭐ 保存对话
                    _save_agent_conversation()
                    st.rerun()
            else:    
                result = agent.invoke(
                    {
                        "messages": st.session_state["agent_state"].get("messages", []),
                        "tender_text": st.session_state["agent_state"]["tender_text"],
                        "company_files": st.session_state["agent_state"].get("company_files", []),
                        "analysis_done": False,
                        "core": None,
                        "all_results": [],
                        "reflection_done": False,
                    },
                    {"configurable": {"thread_id": "main"}}
                )
                st.session_state["agent_has_analyzed"] = True
                st.session_state["agent_state"] = dict(result)
                # ⭐ 保存对话
                _save_agent_conversation()
                st.rerun()
        else:
            from agent import node_chat
            result = node_chat(st.session_state["agent_state"])
            st.session_state["agent_state"] = result
            # ⭐ 保存对话
            _save_agent_conversation()
            st.rerun()






# ========== 统一历史记录 ==========
if st.session_state.get("show_history_all"):
    st.divider()
    st.markdown("## 📜 历史记录")
    
    tab1, tab2, tab3 = st.tabs(["📊 分析记录", "📎 废标报告", "💬 对话记录"])
    
    with tab1:
        from history_db import get_all_history, get_history_detail, delete_history
        records = get_all_history()
        if not records:
            st.info("暂无历史记录")
        else:
            for rec in records:
                rec_id, created_at, tender_name, company_count, best_company = rec
                col1, col2, col3 = st.columns([3, 2, 1])
                with col1:
                    st.write(f"**{tender_name}**")
                    st.caption(f"{created_at} · {company_count}家公司")
                with col2:
                    if best_company:
                        st.write(f"🏆 {best_company}")
                with col3:
                    c1, c2 = st.columns(2)
                    with c1:
                        if st.button("📋", key=f"hist_{rec_id}"):
                            detail = get_history_detail(rec_id)
                            if detail:
                                results = detail["all_results"]
                                st.session_state["all_results"] = detail["all_results"]
                                st.session_state["hidden_risks"] = detail["hidden_risks"]
                                st.session_state["last_risk_rows"] = results[0]["risk_rows"]
                                st.session_state["risk_results"] = results[0]["risk_rows"]
                                st.session_state["last_advice"] = build_advice(results[0]["compare_result"])
                                st.session_state["last_core"] = detail.get("core", {})
                                st.session_state["analysis_ready"] = True
                                st.session_state["show_history_all"] = False
                            st.rerun()
                    with c2:
                        if st.button("🗑", key=f"del_{rec_id}"):
                            delete_history(rec_id)
                            st.rerun()
    
    with tab2:
        from history_db import get_reflection_reports, get_reflection_detail, delete_reflection_report
        from ui_components import print_reflection_report
        reports = get_reflection_reports()
        if not reports:
            st.info("暂无归档报告")
        else:
            for rep in reports:
                rep_id, created_at, tender_name, company_name = rep
                detail = get_reflection_detail(rep_id)
                col_title, col_btn = st.columns([4, 1])
                with col_title:
                    with st.expander(f"{tender_name} — {company_name} ({created_at})", expanded=False):
                        if detail:
                            st.markdown(detail)
                            if st.button("🖨️ 打印", key=f"print_ref_{rep_id}"):
                                print_reflection_report(tender_name, company_name, detail)
                        else:
                            st.caption("（空报告）")
                with col_btn:
                    if st.button("🗑", key=f"del_ref_{rep_id}"):
                        delete_reflection_report(rep_id)
                        st.rerun()
    
    with tab3:
        from history_db import get_conversations, get_conversation, delete_conversation
        conversations = get_conversations()
        if not conversations:
            st.info("暂无保存的对话")
        else:
            for conv in conversations:
                conv_id, created_at, tender_name = conv
                with st.expander(f"{tender_name} — {created_at}", expanded=False):
                    messages = get_conversation(conv_id)
                    for msg in messages:
                        st.chat_message(msg.get("role", "user")).write(msg.get("content", ""))
                    col1, col2 = st.columns([1, 1])
                    with col1:
                        if st.button("🗑", key=f"del_conv_{conv_id}"):
                            delete_conversation(conv_id)
                            st.rerun()
                    with col2:
                        if st.button("📋 恢复对话", key=f"restore_conv_{conv_id}"):
                            if "agent_state" not in st.session_state:
                                st.session_state["agent_state"] ={
                                    "messages": [],
                                    "tender_text": "",
                                    "company_files": [],
                                    "analysis_done": False,
                                    "core": None,
                                    "all_results": [],
                                    "reflection_done": False,
                                }
                            st.session_state["agent_state"]["messages"] = messages
                            st.session_state["agent_has_analyzed"] = True
                            st.session_state["show_history_all"] = False
                            st.rerun()
    
    if st.button("✕ 关闭历史记录"):
        st.session_state["show_history_all"] = False
        st.rerun()