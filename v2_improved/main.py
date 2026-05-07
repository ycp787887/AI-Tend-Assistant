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

# ========== 页面初始化 ==========
setup_page()
inject_print_css()
init_session_state()
# 在页面初始化之后加
if "hidden_risks" not in st.session_state:
    st.session_state["hidden_risks"] = None

# ========== 标题 ==========
st.title("投标文件合规预审助手（双文件自动比对）")

# ========== 侧边栏 ==========
with st.sidebar:
    hidden_risk_clicked = st.button("🔍 一键审计隐藏风险", use_container_width=True)
    if st.button("🖨️ 打开打印报告", use_container_width=True):
        show_print_report()
    st.divider()
    st.markdown("### 📜 历史记录")
    if st.button("查看历史分析", use_container_width=True):
        st.session_state["show_history"] = True    

# ========== API配置 ==========
with st.expander("AI 配置（DeepSeek API）", expanded=False):
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
    "📄 上传招标文件（PDF）", type=["pdf", "txt"], accept_multiple_files=False, key="upload_tender"
)
uploaded_company = st.file_uploader(
    "📄 上传公司资质证明（PDF）", type=["pdf", "txt"], accept_multiple_files=True, key="upload_company"
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
    if uploaded_tender.name != st.session_state.get("tender_file_name") or tender_bytes != st.session_state.get("tender_file_bytes"):
        st.session_state["tender_file_name"] = uploaded_tender.name
        st.session_state["tender_file_bytes"] = tender_bytes
        clear_cached_analysis()

# ✅ 只在文件变化时才更新
if uploaded_company:
    new_files = [{"name": f.name, "bytes": f.getvalue()} for f in uploaded_company]
    old_files = st.session_state.get("company_files", [])
    if new_files != old_files:
        st.session_state["company_files"] = new_files
        clear_cached_analysis()

# 显示状态
if st.session_state.get("tender_file_name"):
    st.info(f"📄 招标文件：{st.session_state['tender_file_name']}")
if st.session_state.get("company_files"):
    count = len(st.session_state["company_files"])
    names = ", ".join([f["name"] for f in st.session_state["company_files"]])
    st.info(f"📄 公司资质（{count}份）：{names}")


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
    disabled=not (st.session_state.get("tender_file_bytes") and st.session_state.get("company_files")),
    use_container_width=True
)

if run_compare:
    logger.info("用户点击「开始比对」")
    try:
        # 1. 解析PDF - 标书
        with st.spinner("📖 正在解析招标文件..."):
            tender_text = extract_pdf_text(st.session_state["tender_file_bytes"])
        if not tender_text.strip():
            st.error("❌ 招标文件未提取到文本，请检查是否为扫描件。")
            st.stop()
        logger.info(f"招标文件解析成功，文本长度: {len(tender_text)} 字符")
        st.session_state["last_full_text"] = tender_text

        # 2. AI提取（或降级兜底）
        if user_key and user_key.strip():
            logger.info("检测到 API Key，使用流式 AI 提取")

            # ===== 提取标书要求（只做1次）=====
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

            # ===== 循环分析每份公司资质 =====
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
                    logger.info(f"{company_name} 缓存未命中，使用流式 AI 提取")
                    display_placeholder = st.empty()
                    full_text = ""
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

            # ===== 多公司汇总 =====
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

            # ===== 保存结果 =====
            if all_results:
                st.session_state["last_core"] = core
                st.session_state["company_profile"] = all_results[0]["profile"]
                st.session_state["last_risk_rows"] = all_results[0]["risk_rows"]
                st.session_state["risk_results"] = all_results[0]["risk_rows"]
                st.session_state["last_advice"] = build_advice(all_results[0]["compare_result"])
                st.session_state["analysis_ready"] = True
                logger.info("分析完成，结果已保存到 session_state")
                st.success("🎉 分析完成！")
                if st.session_state.get("hidden_risks") is None:
                    st.info("💡 点击左侧「一键审计隐藏风险」完善报告，扫描结果将自动存入历史记录。")
                # 保存到历史记录
                from history_db import save_analysis

                tender_name = core.get("项目名称") or "未命名标书"
                if len(all_results) > 1:
                    best_name = min(all_results, key=lambda r: len(r["compare_result"]["missing_certs"]))["name"]
                else:
                    best_name = all_results[0]["name"]

                save_analysis(
                        tender_name, 
                        all_results, 
                        best_name,
                        st.session_state.get("hidden_risks", []),  # ← 加上风险扫描结果
                        core 
                    )
                logger.info(f"已保存到历史记录：{tender_name}，{len(all_results)}家公司，最优：{best_name}")       

        else:
            # ===== 降级方案 =====
            logger.warning("API Key 为空，启用降级方案（正则提取）")
            st.warning("⚠️ 未配置 API Key，当前使用本地规则兜底提取。")
            core = fallback_extract_core_fields(tender_text)

            if not core.get("项目名称") and not core.get("注册资本要求"):
                st.info("💡 正则未能提取到关键信息，建议配置 API Key 以获得准确结果。")

            # 降级只处理第一份
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
    
    # ⭐ 如果是从历史记录加载的，恢复 last_core
    if not st.session_state.get("last_core") and all_results:
        # 从历史数据中重建 last_core（用第一个结果中的标书信息）
        st.session_state["last_core"] = {
            "项目名称": "历史记录",
            "注册资本要求": "",
            "必须具备的资质证书": [],
            "投标截止时间": ""
        }
    
    if len(all_results) > 1:
        company_names = [r["name"] for r in all_results]
        selected = st.selectbox(
            "选择查看的公司", 
            company_names,
            key="selected_company"
        )
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
        st.info(build_advice(selected_result["compare_result"]))
    elif st.session_state.get("risk_results"):
        st.markdown("### 📊 企业匹配结果")
        render_risk_table(st.session_state["risk_results"])
        st.markdown("### 💬 建议")
        st.info(st.session_state.get("last_advice", "暂无建议"))

# ========== 隐藏风险审计 ==========
if hidden_risk_clicked:
    logger.info("用户点击「隐藏风险审计」")
    if not st.session_state.get("last_full_text"):
        logger.warning("隐藏风险审计失败：未完成双文件比对")
        st.warning("请先完成双文件比对")
    elif not user_key.strip():
        logger.warning("隐藏风险审计失败：API Key 为空")
        st.warning("请先填写 API Key")
    else:
        cache_data = get_cache(st.session_state["tender_file_bytes"], "hidden_risks")
        if cache_data is None:
            logger.info("隐藏风险缓存未命中，使用流式 AI 扫描")
            try:
                display_placeholder = st.empty()
                full_text = ""
                for token, current_text in scan_hidden_risks_streaming(
                    st.session_state["last_full_text"], user_key.strip()
                ):
                    full_text = current_text
                    display_placeholder.markdown(
                        f"### 🔍 AI 正在扫描隐藏风险...\n\n```json\n{full_text}▌\n```"
                    )
                risks = parse_risk_streaming_result(full_text)
                display_placeholder.markdown(
                    f"### ✅ 隐藏风险扫描完成\n\n```json\n{json.dumps({'risks': risks}, ensure_ascii=False, indent=2)}\n```"
                )
                set_cache(st.session_state["tender_file_bytes"], "hidden_risks", {"risks": risks})
                st.session_state["hidden_risks"] = risks

                # 更新最近一条历史记录的风险数据
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
# ========== 历史记录 ==========
if st.session_state.get("show_history"):
    from history_db import get_all_history, get_history_detail, delete_history
    
    st.divider()
    st.markdown("## 📜 历史分析记录")
    
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
                    if st.button("📋", key=f"hist_{rec_id}", help="查看详情"):
                        logger.info(f"回看历史记录 ID={rec_id}：{tender_name}")
                        detail = get_history_detail(rec_id)
                        if detail:
                            results = detail["all_results"]
                            st.session_state["all_results"] = detail["all_results"]
                            st.session_state["hidden_risks"] = detail["hidden_risks"]  # ← 恢复风险扫描
                            st.session_state["last_risk_rows"] = results[0]["risk_rows"]
                            st.session_state["risk_results"] = results[0]["risk_rows"]
                            st.session_state["last_advice"] = build_advice(results[0]["compare_result"])
                            st.session_state["last_core"] = detail.get("core", {})  # ← 恢复标书信息
                            st.session_state["analysis_ready"] = True
                            st.session_state["show_history"] = False
                        st.rerun()
                with c2:
                    if st.button("🗑", key=f"del_{rec_id}", help="删除记录"):
                        logger.info(f"删除历史记录 ID={rec_id}：{tender_name}")
                        delete_history(rec_id)
                        st.rerun()
                   