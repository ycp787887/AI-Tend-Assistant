# risk_scanner.py
# 这个文件负责：扫描霸王条款、扣分项等隐藏风险
# 想改扫描什么内容？改AI提示词

import json
from openai import OpenAI
from config import DEEPSEEK_BASE_URL, DEEPSEEK_MODEL, LLM_TIMEOUT_SECONDS
from retry_handler import with_retry
from logger_config import logger


@with_retry
def scan_hidden_risks_with_ai(raw_text: str, api_key: str) -> list[str]:
    """用AI扫描全文，找出表格之外的隐藏风险"""
    logger.info(f"开始扫描隐藏风险，文本长度: {len(raw_text)} 字符")  # ← 加（移到函数体内）
    
    client = OpenAI(
        api_key=api_key,
        base_url=DEEPSEEK_BASE_URL,
        timeout=LLM_TIMEOUT_SECONDS,
        max_retries=0,
    )
    
    # ===== 想改扫描的风险类型？改下面这个提示词 =====
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
    # ===== 提示词结束 =====
    
    logger.info("发送隐藏风险扫描请求到 API")  # ← 加
    
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
    logger.info(f"API 返回内容长度: {len(content)} 字符")  # ← 加
    
    data = json.loads(content)
    risks = data.get("risks", [])
    if not isinstance(risks, list):
        logger.warning("API 返回的 risks 不是列表，返回空列表")  # ← 加
        return []
    
    result = [str(r).strip() for r in risks if str(r).strip()]
    
    if result:
        logger.info(f"隐藏风险扫描完成，发现 {len(result)} 个风险项")  # ← 加
        for i, risk in enumerate(result, 1):
            logger.info(f"  风险{i}: {risk[:100]}...")  # ← 加（只记录前100字）
    else:
        logger.info("隐藏风险扫描完成，未发现明显风险")  # ← 加
    
    return result