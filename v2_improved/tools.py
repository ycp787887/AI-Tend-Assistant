# tools.py
"""
外部工具集 - 完全独立，不依赖 Agent 状态
"""
from datetime import datetime, date
import re
from logger_config import logger


def calculate_deadline_days(deadline_str: str) -> str:
    """计算距离投标截止还有多少天，直接返回可展示的消息"""
    logger.info(f"工具调用：计算截止天数，输入={deadline_str}")
    
    try:
        date_match = re.search(
            r'(\d{4})\s*[年/\-]\s*(\d{1,2})\s*[月/\-]\s*(\d{1,2})',
            deadline_str
        )
        
        if not date_match:
            return f"无法从'{deadline_str}'中解析日期。"
        
        year, month, day = int(date_match.group(1)), int(date_match.group(2)), int(date_match.group(3))
        deadline_date = date(year, month, day)
        today = date.today()
        days_left = (deadline_date - today).days
        
        if days_left < 0:
            return f"截止日期{deadline_date}已过{abs(days_left)}天。"
        elif days_left == 0:
            return "今天就是截止日期！请立即提交。"
        elif days_left <= 7:
            return f"距离截止日期{deadline_date}仅剩{days_left}天，非常紧迫！"
        else:
            return f"距离截止日期{deadline_date}还有{days_left}天。"
            
    except Exception as e:
        logger.error(f"计算截止天数失败: {e}")
        return f"计算失败：{e}"


# 工具路由表：关键词 → (处理函数, 需要的数据)
TOOL_ROUTER = {
    "deadline": {
        "keywords": ["多少天", "还剩几天", "倒计时", "还有几天", "投标截止"],
        "handler": calculate_deadline_days,
        "data_key": "投标截止时间"  # 从 core 里取哪个字段
    }
}


def classify_intent(user_input: str, api_key: str) -> str:
    """用 AI 判断用户意图"""
    from openai import OpenAI
    from config import DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
    
    client = OpenAI(
        api_key=api_key,
        base_url=DEEPSEEK_BASE_URL,
        timeout=10,
        max_retries=0,
    )
    
    prompt = f"""判断用户意图，只回复一个词：
- deadline：询问投标截止时间或剩余天数（如"还有几天""截止时间"）
- cert：询问某个具体资质证书的办理要求、周期、费用（如"ISO 27001好办吗""这个证书要多久"）
- partner：询问如何找联合体合作伙伴（如"怎么找联合体""哪里找合作伙伴"）
- chat：其他问题，包括分析公司、对比公司优劣、追问某公司缺什么证书、注册资本是否达标等

用户：{user_input}
意图："""
    
    response = client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        temperature=0,
        max_tokens=10,
        messages=[{"role": "user", "content": prompt}],
    )
    
    intent = response.choices[0].message.content.strip().lower()
    logger.info(f"意图分类：{user_input[:30]}... → {intent}")
    return intent





def try_handle_with_tool(user_input: str, core: dict, api_key: str) -> str | None:
    intent = classify_intent(user_input, api_key)
    
    if intent == "deadline":
        data = core.get("投标截止时间", "") if core else ""
        if data:
            return calculate_deadline_days(data)
        else:
            return "标书中未提取到投标截止时间。"
    
    elif intent == "cert":
        return search_cert_info(user_input)
    
    elif intent == "partner":
        return search_partner(user_input)
    
    else:
        return None  # 走聊天




def search_cert_info(cert_name: str) -> str:
    """
    搜索资质证书的办理要求和周期
    注：当前为规则匹配版，后续可接入真实搜索API
    """
    cert_database = {
        "iso": "ISO认证办理周期约3-6个月，需通过国家认可的认证机构审核。费用约2-10万，需提供管理体系文件和运行记录。",
        "27001": "ISO/IEC 27001信息安全管理体系认证：办理周期3-6个月，需建立ISMS体系并运行至少3个月，通过CCAA认可的审核机构认证。",
        "9001": "ISO 9001质量管理体系认证：办理周期2-4个月，需建立质量管理体系并运行至少3个月。",
        "建筑": "建筑业资质分为特级、一级、二级、三级，由住房和城乡建设部门审批，办理周期3-6个月，需满足注册资本、人员、业绩等条件。",
        "安全": "安全生产许可证由住建部门颁发，办理周期1-3个月，需具备安全生产条件和特种作业人员证书。",
        "营业项目登记": "营业项目登记由经济部办理，周期约1-2周，需提交公司变更登记申请书及营业项目变更说明。",
    }
    
    cert_lower = cert_name.lower()
    for key, info in cert_database.items():
        if key in cert_lower or cert_lower in key:
            return f"关于「{cert_name}」：{info}"
    
    return f"关于「{cert_name}」：建议访问相关主管部门官网查询最新办理要求。一般资质证书办理需准备企业基本资料、相关证明文件，周期1-6个月不等。"


def search_partner(cert_name: str) -> str:
    """
    搜索潜在的联合体合作伙伴
    注：当前为示例版，实际可接入企查查/天眼查API
    """
    return (
        f"关于联合「{cert_name}」的合作伙伴建议：\n"
        f"1. 可在政府采购网查询持有该资质的供应商名录\n"
        f"2. 建议联系本地行业协会获取会员名单\n"
        f"3. 可考虑与具备该资质的系统集成商组成联合体\n"
        f"4. 注意：需确认标书是否接受联合体投标"
    )


# ⭐ 更新 TOOL_ROUTER，加入新工具
TOOL_ROUTER = {
    "cert_search": {
        "keywords": ["好办吗", "难办吗", "怎么办理", "办理要求", "周期", "费用"],
        "handler": search_cert_info,
        "data_key": None
    },
    "partner_search": {
        "keywords": ["联合体", "合作伙伴", "找谁", "哪里找", "联合投标"],
        "handler": search_partner,
        "data_key": None
    },
    "deadline": {
        "keywords": ["多少天", "还剩几天", "倒计时", "还有几天", "投标截止"],
        "handler": calculate_deadline_days,
        "data_key": "投标截止时间"
    }
}