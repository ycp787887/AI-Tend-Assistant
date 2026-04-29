# risk_scanner.py
# 这个文件负责：扫描霸王条款、扣分项等隐藏风险
# 想改扫描什么内容？改AI提示词

import json
from typing import Generator
from openai import OpenAI
from config import DEEPSEEK_BASE_URL, DEEPSEEK_MODEL, LLM_TIMEOUT_SECONDS
from retry_handler import with_retry
from logger_config import logger


@with_retry
def scan_hidden_risks_streaming(raw_text: str, api_key: str) -> Generator:
    """
    流式AI扫描隐藏风险——逐字返回
    用于打字机效果展示
    """
    logger.info(f"开始流式扫描隐藏风险，文本长度: {len(raw_text)} 字符")
    
    client = OpenAI(
        api_key=api_key,
        base_url=DEEPSEEK_BASE_URL,
        timeout=LLM_TIMEOUT_SECONDS,
        max_retries=0,
    )
    
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
    
    logger.info("发送流式请求到 DeepSeek API")
    response = client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        temperature=0,
        stream=True,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": "你只返回合法 JSON。"},
            {"role": "user", "content": prompt},
        ],
    )
    
    full_text = ""
    for chunk in response:
        if chunk.choices[0].delta.content:
            token = chunk.choices[0].delta.content
            full_text += token
            yield token, full_text
    
    logger.info(f"流式扫描完成，总长度: {len(full_text)} 字符")


def parse_risk_streaming_result(full_text: str) -> list[str]:
    """解析流式扫描结果"""
    try:
        data = json.loads(full_text)
    except json.JSONDecodeError:
        data = {}
    
    risks = data.get("risks", [])
    if not isinstance(risks, list):
        logger.warning("API 返回的 risks 不是列表，返回空列表")
        return []
    
    result = [str(r).strip() for r in risks if str(r).strip()]
    
    if result:
        logger.info(f"隐藏风险扫描完成，发现 {len(result)} 个风险项")
        for i, risk in enumerate(result, 1):
            logger.info(f"  风险{i}: {risk[:100]}...")
    else:
        logger.info("隐藏风险扫描完成，未发现明显风险")
    
    return result


# ========== 保留原版（兼容性）==========
@with_retry
def scan_hidden_risks_with_ai(raw_text: str, api_key: str) -> list[str]:
    """原版非流式扫描（保留作为备用）"""
    full_text = ""
    for _, current_text in scan_hidden_risks_streaming(raw_text, api_key):
        full_text = current_text
    return parse_risk_streaming_result(full_text)