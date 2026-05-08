# chat.py
"""
对话式追问模块
- 用户可以在分析结果下方追问细节
- 上下文自动包含标书要求和公司资质
"""
import streamlit as st
from openai import OpenAI
from config import DEEPSEEK_BASE_URL, DEEPSEEK_MODEL, LLM_TIMEOUT_SECONDS
from logger_config import logger


def build_context(question: str) -> str:
    """
    构建发给AI的上下文
    包含：标书要求 + 当前选中的公司资质 + 用户问题
    """
    last_core = st.session_state.get("last_core", {})
    all_results = st.session_state.get("all_results", [])
    
    # 获取当前选中的公司
    selected = st.session_state.get("selected_company", "")
    current_company = None
    for r in all_results:
        if r["name"] == selected:
            current_company = r
            break
    if not current_company and all_results:
        current_company = all_results[0]
    
    # 拼上下文
    context = "以下是一次投标分析的结果：\n\n"
    context += f"【标书要求】\n{last_core}\n\n"
    
    if current_company:
        context += f"【当前公司：{current_company['name']}】\n"
        context += f"资质信息：{current_company['profile']}\n"
        context += f"对比结果：{current_company['risk_rows']}\n"
    
    context += f"\n【用户追问】\n{question}"
    
    return context


def ask_followup(question: str, api_key: str):
    """
    处理用户追问，流式返回AI回答
    """
    if not question.strip():
        return
    
    client = OpenAI(
        api_key=api_key,
        base_url=DEEPSEEK_BASE_URL,
        timeout=LLM_TIMEOUT_SECONDS,
        max_retries=0,
    )
    
    context = build_context(question)
    
    logger.info(f"用户追问：{question[:50]}...")
    
    response = client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        temperature=0.3,
        stream=True,
        messages=[
            {"role": "system", "content": "你是招投标分析助手，基于已有的分析数据回答用户问题。回答简洁、直接，用中文。"},
            {"role": "user", "content": context},
        ],
    )
    
    # 流式输出
    answer_placeholder = st.empty()
    full_answer = ""
    for chunk in response:
        if chunk.choices[0].delta.content:
            token = chunk.choices[0].delta.content
            full_answer += token
            answer_placeholder.markdown(full_answer + "▌")
    
    answer_placeholder.markdown(full_answer)
    logger.info(f"AI回答完成，长度：{len(full_answer)} 字符")
    
    return full_answer


def render_chat_section(user_key: str):
    """
    渲染追问聊天区域
    """
    st.divider()
    st.markdown("## 💬 追问助手")
    st.caption("基于当前分析结果，你可以向AI追问任何细节问题。")
    
    # 初始化聊天历史
    if "chat_history" not in st.session_state:
        st.session_state["chat_history"] = []
    
    # 显示历史对话
    for msg in st.session_state["chat_history"]:
        if msg["role"] == "user":
            st.chat_message("user").write(msg["content"])
        else:
            st.chat_message("assistant").write(msg["content"])
    
    # 输入框
    question = st.chat_input("输入你的问题，例如：这家公司的注册资本够吗？")
    
    if question:
        # 显示用户消息
        st.chat_message("user").write(question)
        st.session_state["chat_history"].append({"role": "user", "content": question})
        
        # 获取AI回答
        with st.chat_message("assistant"):
            answer = ask_followup(question, user_key)
        
        # 保存到历史
        st.session_state["chat_history"].append({"role": "assistant", "content": answer})
        
        st.rerun()