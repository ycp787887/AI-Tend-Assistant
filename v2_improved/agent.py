# agent.py
"""
LangGraph Agent
- 自主决策分析流程
- 可用工具：RAG检索、结构化提取、多公司对比、追问
"""
import streamlit as st
from typing import TypedDict, Annotated
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from logger_config import logger


# ========== 1. 定义状态 ==========
class AgentState(TypedDict):
    """Agent 的记忆"""
    messages: Annotated[list, "对话历史"]
    tender_text: str
    company_files: list
    analysis_done: bool
    core: dict | None
    all_results: list


# ========== 2. 定义工具节点 ==========

def node_extract_tender(state: AgentState) -> AgentState:
    """提取标书要求"""
    from tender_extractor import extract_core_fields_structured
    
    api_key = st.session_state.get("user_key", "")
    if not api_key:
        state["messages"].append({"role": "assistant", "content": "请先配置 API Key。"})
        return state
    
    logger.info("Agent：开始提取标书要求")
    core = extract_core_fields_structured(state["tender_text"], api_key)
    state["core"] = core
    
    state["messages"].append({
        "role": "assistant",
        "content": f"已提取标书要求：项目名={core.get('项目名称', '未提取')}，"
                   f"注册资本要求={core.get('注册资本要求', '未提取')}，"
                   f"需{len(core.get('必须具备的资质证书', []))}项资质证书。"
    })
    
    return state


def node_analyze_companies(state: AgentState) -> AgentState:
    """分析所有公司"""
    from company_extractor import extract_company_profile_structured
    from comparator import compare_with_company_profile
    from report_builder import build_risk_rows
    
    api_key = st.session_state.get("user_key", "")
    if not api_key or not state.get("core"):
        state["messages"].append({"role": "assistant", "content": "请先完成标书提取。"})
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
    # ⭐ 同步到 session_state
    if all_results:
        st.session_state["all_results"] = all_results
        st.session_state["last_risk_rows"] = all_results[0]["risk_rows"]
        st.session_state["risk_results"] = all_results[0]["risk_rows"]
    
    # 汇总
    summary = "分析完成：\n"
    for r in all_results:
        missing = len(r["compare_result"]["missing_certs"])
        capital = "✅" if not r["compare_result"]["capital_not_met"] else "✖"
        summary += f"- {r['name']}：注册资本{capital}，缺失{missing}项证书\n"
    
    if len(all_results) > 1:
        best = min(all_results, key=lambda r: len(r["compare_result"]["missing_certs"]))
        summary += f"\n🏆 推荐：{best['name']}"
    
    state["messages"].append({"role": "assistant", "content": summary})
    
    return state

def node_chat(state: AgentState) -> AgentState:
    """回答用户问题——直接用 agent_state 的数据"""
    from openai import OpenAI
    from config import DEEPSEEK_BASE_URL, DEEPSEEK_MODEL, LLM_TIMEOUT_SECONDS
    
    api_key = st.session_state.get("user_key", "")
    last_msg = state["messages"][-1]["content"] if state["messages"] else ""
    
    if not state.get("analysis_done"):
        state["messages"].append({
            "role": "assistant",
            "content": "请先上传文件并开始分析，然后我可以回答具体问题。"
        })
        return state
    
    # 直接用 agent_state 的数据构建上下文
    context = "以下是一次投标分析的结果：\n\n"
    context += f"【标书要求】\n{state.get('core', {})}\n\n"
    
    # 智能匹配公司
    if state.get("all_results"):
        context += "【所有公司分析结果】\n"
        for r in state["all_results"]:
            context += f"--- {r['name']} ---\n"
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
    
    state["messages"].append({"role": "assistant", "content": full_answer})
    
    # 同步到 session_state
    if state.get("core"):
        st.session_state["last_core"] = state["core"]
    if state.get("all_results"):
        st.session_state["all_results"] = state["all_results"]
        st.session_state["analysis_ready"] = True
    
    return state


# ========== 3. 定义路由 ==========

def router(state: AgentState) -> str:
    """决定下一步做什么"""
    last_msg = state["messages"][-1]["content"].lower() if state["messages"] else ""
    
    # 用户要分析
    if any(kw in last_msg for kw in ["分析", "对比", "比对", "比较"]):
        if not state.get("core"):
            return "extract"
        elif state.get("company_files") and not state.get("analysis_done"):
            return "analyze_companies"
    # ⭐ 已分析完，直接聊天
    if state.get("analysis_done"):
        return "chat"
    
    # 用户提问
    if state.get("analysis_done"):
        return "chat"
    
    return "chat"


# ========== 4. 构建图 ==========

def build_agent():
    """构建 Agent 流程图"""
    workflow = StateGraph(AgentState)
    
    # 添加节点
    workflow.add_node("extract", node_extract_tender)
    workflow.add_node("analyze_companies", node_analyze_companies)
    workflow.add_node("chat", node_chat)
    
    # 设置入口
    workflow.set_conditional_entry_point(
        lambda state: "chat" if state.get("analysis_done") else "extract",
        {"extract": "extract", "chat": "chat"}
)
    
    # 连线
    workflow.add_edge("extract", "analyze_companies")
    workflow.add_conditional_edges(
        "analyze_companies",
        lambda state: "chat" if state.get("analysis_done") else "analyze_companies",
        {"chat": "chat", "analyze_companies": "analyze_companies"}
    )
    workflow.add_edge("chat", END)
    
    # 编译
    memory = MemorySaver()
    app = workflow.compile(checkpointer=memory)
    
    return app