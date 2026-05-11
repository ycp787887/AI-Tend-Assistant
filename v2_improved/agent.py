# agent.py
"""
LangGraph Agent
- 自主决策分析流程
- 工具调用已独立到 main.py，这里只负责分析和聊天
"""
import streamlit as st
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from logger_config import logger
from typing import TypedDict, Annotated
import operator

# ========== 1. 定义状态 ==========
class AgentState(TypedDict):
    messages: Annotated[list, operator.add]
    tender_text: str
    company_files: list
    analysis_done: bool
    core: dict | None
    all_results: list
    reflection_done: bool

# ========== 2. 分析节点 ==========

def node_extract_tender(state: AgentState) -> AgentState:
    """提取标书要求"""
    from tender_extractor import extract_core_fields_structured
    
    api_key = st.session_state.get("user_key", "")
    if not api_key:
        state["messages"] = state.get("messages", []) + [
            {"role": "assistant", "content": "请先配置 API Key。"}
        ]
        return state
    
    logger.info("Agent：开始提取标书要求")
    core = extract_core_fields_structured(state["tender_text"], api_key)
    state["core"] = core
    
    state["messages"] = state.get("messages", []) + [{
        "role": "assistant",
        "content": f"已提取标书要求：项目名={core.get('项目名称', '未提取')}，"
                   f"注册资本要求={core.get('注册资本要求', '未提取')}，"
                   f"需{len(core.get('必须具备的资质证书', []))}项资质证书。"
    }]
    
    return state


def node_analyze_companies(state: AgentState) -> AgentState:
    """分析所有公司"""
    from company_extractor import extract_company_profile_structured
    from comparator import compare_with_company_profile
    from report_builder import build_risk_rows
    
    api_key = st.session_state.get("user_key", "")
    if not api_key or not state.get("core"):
        state["messages"] = state.get("messages", []) + [
            {"role": "assistant", "content": "请先完成标书提取。"}
        ]
        return state
    
    all_results = []
    for company_file in state["company_files"]:
        company_name = company_file["name"]
        company_text = company_file.get("text", "")
        
        logger.info(f"Agent：分析公司 {company_name}")
        profile = extract_company_profile_structured(company_text, api_key)
        compare = compare_with_company_profile(state["core"], profile)
        risk = build_risk_rows(state["core"], compare)
        
        all_results.append({
            "name": company_name,
            "profile": profile,
            "compare_result": compare,
            "risk_rows": risk
        })
    
    state["all_results"] = all_results
    state["analysis_done"] = True
    
    if all_results:
        st.session_state["all_results"] = all_results
    
    return state


def node_reflect(state: AgentState) -> AgentState:
    """反思节点：硬性约束检查"""
    from reflector import (
        hard_constraint_check, generate_reflection_summary,
        check_joint_venture, generate_decision_matrix,
        generate_archivable_report, generate_action_kit
    )
    
    if state.get("reflection_done"):
        return state
    
    state["all_results"] = hard_constraint_check(state["all_results"], state.get("core", {}))
    summary = generate_reflection_summary(state["all_results"], state.get("core", {}))
    
    jv = check_joint_venture(state.get("tender_text", ""))
    matrix = generate_decision_matrix(state["all_results"], jv, state.get("core", {}))
    
    failed = [r for r in state["all_results"] if r.get("status") == "fail"]
    archive = ""
    if failed:
        archive = generate_archivable_report(failed[0], state.get("core", {}), jv)
        # 保存到历史数据库
        from history_db import save_reflection_report
        save_reflection_report(
            tender_name=state.get("core", {}).get("项目名称", "未命名"),
            company_name=failed[0]["name"],
            report=archive
        )
    
    action_kit = generate_action_kit(jv, state.get("core", {}))
    
    full_reflection = summary + matrix + archive + action_kit
    
    state["messages"] = state.get("messages", []) + [
        {"role": "assistant", "content": full_reflection}
    ]
    state["reflection_done"] = True
    
    return state


def node_chat(state: AgentState) -> AgentState:
    """回答用户问题——纯AI聊天，不处理工具"""
    from openai import OpenAI
    from config import DEEPSEEK_BASE_URL, DEEPSEEK_MODEL, LLM_TIMEOUT_SECONDS
    import os
    
    api_key = (
        st.session_state.get("user_key", "") or
        os.getenv("DEEPSEEK_API_KEY", "") or
        os.getenv("OPENAI_API_KEY", "")
    )
    
    if not api_key:
        state["messages"] = state.get("messages", []) + [
            {"role": "assistant", "content": "API Key 未配置。"}
        ]
        return state
    
    last_msg = state["messages"][-1]["content"] if state.get("messages") else ""
    
    if not state.get("analysis_done"):
        state["messages"] = state.get("messages", []) + [
            {"role": "assistant", "content": "请先上传文件并开始分析。"}
        ]
        return state
    
    context = "以下是一次投标分析的结果：\n\n"
    context += f"【标书要求】\n{state.get('core', {})}\n\n"
    
    if state.get("all_results"):
        context += "【所有公司分析结果】\n"
        for r in state["all_results"]:
            context += f"--- {r['name']} ---\n"
            context += f"状态：{r.get('status', '未判定')}\n"
            if r.get("label"):
                context += f"标签：{r['label']}\n"
            context += f"公司资质：{r['profile']}\n"
            context += f"缺失的证书：{r['compare_result'].get('missing_certs', [])}\n"
            capital_ok = "达标" if not r['compare_result']['capital_not_met'] else "不达标"
            context += f"注册资本：{capital_ok}\n\n"
    
    context += f"\n【用户追问】\n{last_msg}"
    
    client = OpenAI(
        api_key=api_key,
        base_url=DEEPSEEK_BASE_URL,
        timeout=LLM_TIMEOUT_SECONDS,
        max_retries=0,
    )
    
    response = client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        temperature=0.3,
        stream=True,
        messages=[
            {"role": "system", "content": "你是招投标分析助手，基于已有的分析数据回答用户问题。回答简洁、直接，用中文。"},
            {"role": "user", "content": context},
        ],
    )
    
    full_answer = ""
    for chunk in response:
        if chunk.choices[0].delta.content:
            full_answer += chunk.choices[0].delta.content
    
    state["messages"] = state.get("messages", []) + [
        {"role": "assistant", "content": full_answer}
    ]
    
    if state.get("core"):
        st.session_state["last_core"] = state["core"]
    if state.get("all_results"):
        st.session_state["all_results"] = state["all_results"]
        st.session_state["analysis_ready"] = True
    
    return state


# ========== 3. 构建图 ==========
def build_agent():
    workflow = StateGraph(AgentState)
    
    workflow.add_node("extract", node_extract_tender)
    workflow.add_node("analyze_companies", node_analyze_companies)
    workflow.add_node("reflect", node_reflect)
    workflow.add_node("chat", node_chat)
    
    workflow.set_entry_point("extract")
    workflow.add_edge("extract", "analyze_companies")
    workflow.add_edge("analyze_companies", "reflect")
    workflow.add_edge("reflect", "chat")
    workflow.add_edge("chat", END)
    
    memory = MemorySaver()
    app = workflow.compile(checkpointer=memory)
    
    return app