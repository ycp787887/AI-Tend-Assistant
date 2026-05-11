# reflector.py
"""
反思机制 - 硬性约束检查器
在所有分析之后、展示之前，对每家公司做生死判定
"""
from logger_config import logger


def hard_constraint_check(all_results: list, core: dict) -> list:
    """
    硬性约束检查：给每家公司打上标签
    
    返回：更新后的 all_results，每家多了 status 和 label 字段
    - status: "pass" | "fail"
    - label: str，失败原因
    """
    required_capital = core.get("注册资本要求", "")
    
    for r in all_results:
        issues = []
        
        # 1. 注册资本检查
        if r["compare_result"]["capital_not_met"]:
            company_capital = r["profile"].get("公司注册资本", "未知")
            issues.append(f"注册资本不达标（要求{required_capital}，实际{company_capital}）")
        
        # 2. 证书全缺检查（一项都没有）
        company_certs = r["profile"].get("持有的证书列表", [])
        required_certs = core.get("必须具备的资质证书", [])
        if required_certs and not company_certs:
            issues.append("未持有任何标书要求的资质证书")
        
        # 3. 判定
        if issues:
            r["status"] = "fail"
            r["label"] = "；".join(issues)
        else:
            r["status"] = "pass"
            r["label"] = ""
        
        logger.info(f"反思判定：{r['name']} → {r['status']} {r['label']}")
    
    return all_results


def generate_reflection_summary(all_results: list, core: dict) -> str:
    """
    生成反思摘要，注入到 Agent 的消息中
    """
    fail_count = sum(1 for r in all_results if r.get("status") == "fail")
    pass_count = sum(1 for r in all_results if r.get("status") == "pass")
    
    summary = "## 🔍 硬性约束检查结果\n\n"
    
    for r in all_results:
        if r.get("status") == "fail":
            summary += f"**废标公司**：{r['name']}\n\n"
            summary += f"**原因**：{r['label']}\n\n"
            summary += f"该公司不满足硬性要求，已从推荐列表中排除。\n\n"
        else:
            summary += f"✅ {r['name']}：通过硬性检查\n"
            summary += f"可进入后续详细评估。\n\n"
    
    if pass_count > 0:
        summary += f"\n✅ 通过公司可进入详细对比，点击左侧「🔍 一键审计隐藏风险」和「🖨️ 打开打印报告」生成正式投标文件。\n"
    
    if fail_count > 0 and pass_count > 0:
        summary += f"**结论**：{fail_count}家废标，后续仅分析{pass_count}家通过的公司。\n"
        
    elif fail_count == len(all_results):
        summary += f"**结论**：所有公司均不满足硬性要求，建议重新寻找投标方或启动联合体方案。\n"
    elif pass_count == len(all_results):
        summary += f"**结论**：所有公司均通过硬性检查，可进入详细评估。\n"
    return summary

def check_joint_venture(tender_text: str) -> dict:
    """
    检查标书对联合体的态度，区分三种情况
    返回：{"status": "forbidden"|"allowed"|"unclear", "clause": str, "quote": str}
    """
    # 明确禁止
    forbid_keywords = [
        "不接受联合体", "不允許聯合體", "不接受联合投标",
        "禁止联合体", "禁止聯合體", "不得采用联合体"
    ]
    for kw in forbid_keywords:
        if kw in tender_text:
            return {
                "status": "forbidden",
                "clause": f"标书明确禁止联合体投标。",
                "quote": kw
            }
    
    # 明确允许
    allow_keywords = [
        "接受联合体", "允許聯合體", "联合体投标", "聯合體投標",
        "允许联合体", "允许聯合體"
    ]
    for kw in allow_keywords:
        if kw in tender_text:
            return {
                "status": "allowed",
                "clause": f"标书明确允许联合体投标。",
                "quote": kw
            }
    
    # 未提及
    return {
        "status": "unclear",
        "clause": "标书未明确禁止或允许联合体。依据多数地区招投标法规，未禁止即视为允许。",
        "quote": ""
    }



def generate_escape_plan(all_results: list, core: dict, tender_text: str) -> dict:
    failed = [r for r in all_results if r.get("status") == "fail"]
    if not failed:
        return {"plan": "", "recommendation": ""}
    
    jv = check_joint_venture(tender_text)
    sample = failed[0]
    missing = sample["compare_result"]["missing_certs"]
    
    if jv["allowed"]:
        plan = (
            f"\n🆘 **逃生方案：联合体投标**\n\n"
            f"废标公司：**{sample['name']}**\n\n"
            f"缺失资质：{'、'.join(missing) if missing else '无'}\n\n"
            f"联合体依据：{jv['clause']}\n\n"
            f"建议动作：\n"
            f"1. 寻找持有{'、'.join(missing[:2])}的合作伙伴\n"
            f"2. 组建联合体，重新提交投标\n"
            f"3. 在投标文件中附上联合体协议\n\n"
        )
    else:
        plan = (
            f"\n## ❌ 无法投标\n\n"
            f"**废标公司**：{sample['name']}\n\n"
            f"**缺失资质**：{'、'.join(missing) if missing else '无'}\n\n"
            f"**联合体条款**：未找到\n\n"
            f"**该标书不允许联合体，且硬性条件不满足。建议放弃本项目。**\n\n"
        )
    
    return {"plan": plan, "recommendation": ""}


def generate_decision_matrix(all_results: list, jv_result: dict, core: dict = None) -> str:
    """决策消元矩阵——穷举所有可能路径，含历史公司"""
    matrix = "\n## 📋 决策消元矩阵（全量）\n\n"
    matrix += "| 路径 | 可行性 | 依据 |\n"
    matrix += "|------|--------|------|\n"
    
    # 1. 当前分析的公司
    for r in all_results:
        if r.get("status") == "fail":
            matrix += f"| {r['name']} 独立投标 | ❌ 废标 | {r['label']} |\n"
        else:
            label = r.get("label", "满足硬性要求")
            matrix += f"| {r['name']} 独立投标 | ✅ 通过 | 满足硬性要求 |\n"
    
    # 2. 历史记录中的公司（从 history_db 拉取）
    try:
        from history_db import get_all_history, get_history_detail
        
        tender_name = core.get("项目名称", "") if core else ""
        if tender_name:
            history_records = get_all_history()
            for rec in history_records:
                rec_id, created_at, hist_tender, company_count, best_company = rec
                # 只取同标书的记录
                if hist_tender == tender_name:
                    detail = get_history_detail(rec_id)
                    if detail:
                        results = detail.get("all_results", [])
                        for r in results:
                            # 避免重复当前分析的公司
                            if not any(r["name"] == cur.get("name") for cur in all_results):
                                missing = len(r.get("compare_result", {}).get("missing_certs", []))
                                capital_ok = not r.get("compare_result", {}).get("capital_not_met", True)
                                if not capital_ok or missing > 0:
                                    matrix += f"| {r['name']} 独立投标 | ❌ 废标 | 缺{missing}项资质（{created_at}记录） |\n"
    except:
        pass  # 数据库不可用时跳过
    
    # 3. 联合体路径
    if jv_result["status"] == "forbidden":
        matrix += f"| 联合体投标 | ❌ 禁止 | {jv_result['quote']} |\n"
        matrix += f"\n📌 **最终裁决**：所有路径法律窗口均已关闭，建议放弃本项目。\n"
    elif jv_result["status"] == "allowed":
        matrix += f"| 联合体投标 | ✅ 允许 | {jv_result['quote']} |\n"
        matrix += f"\n📌 **最终裁决**：联合体路径开放，建议立即启动伙伴匹配。\n"
    else:
        matrix += f"| 联合体投标 | ⚠️ 需确认 | 标书未明确 |\n"
        matrix += f"\n📌 **最终裁决**：联合体条款未明确，建议电联招标方确认后决定。\n"
    
    return matrix

def generate_archivable_report(failed_company: dict, core: dict, jv_result: dict) -> str:
    """可复盘的废标归档报告——附原文引用"""
    report = "\n## 📎 废标归档报告\n\n"
    report += f"**判定对象**：{failed_company['name']}\n\n"
    
    # 注册资本
    report += "### 硬性条款1：注册资本\n"
    report += f"- 要求：{core.get('注册资本要求', '未提取')}\n"
    report += f"- 实际：{failed_company['profile'].get('公司注册资本', '未提取')}\n"
    report += f"- 标书原文：\"{core.get('注册资本要求', '见标书')}\"\n"
    report += f"- 判定：不满足，废标。\n\n"
    
    # 资质证书
    missing = failed_company['compare_result']['missing_certs']
    if missing:
        report += "### 硬性条款2：资质证书\n"
        report += f"- 要求：{len(core.get('必须具备的资质证书', []))}项\n"
        report += f"- 缺失：{'、'.join(missing)}\n"
        report += f"- 标书原文：\"{', '.join(core.get('必须具备的资质证书', []))}\"\n"
        report += f"- 判定：不满足，废标。\n\n"
    
    # 替代方案
    report += "### 替代方案穷举\n"
    report += f"- 独立投标：❌ 硬性条款不满足\n"
    if jv_result["status"] == "forbidden":
        report += f"- 联合体：❌ 标书明确禁止（\"{jv_result['quote']}\"）\n"
    elif jv_result["status"] == "allowed":
        report += f"- 联合体：✅ 标书允许\n"
    else:
        report += f"- 联合体：⚠️ 需确认\n"
    
    report += f"\n**归档建议**：标记该公司为不合格，避免同类资质企业重复评估。\n"
    
    return report



def generate_action_kit(jv_result: dict, core: dict) -> str:
    if jv_result["status"] != "unclear":
        return ""
    
    tender_name = core.get("项目名称", "___________")
    contact_name = core.get("招标联系人", "")
    contact_phone = core.get("联系电话", "")
    
    contact_info = ""
    if contact_name and contact_phone:
        contact_info = f"{contact_name}（{contact_phone}）"
    elif contact_phone:
        contact_info = contact_phone
    
    kit = "\n## ⚡️ 行动工具包\n\n"
    kit += "**核心问题**：\"请问是否接受联合体投标？\"\n\n"
    kit += "**备用问题**：\"如接受，对联合体各成员的资质和业绩有什么具体要求？\"\n\n"
    
    kit += "**记录模板**：\n"
    kit += "```\n"
    kit += f"通话日期：____年__月__日\n"
    kit += f"招标项目：{tender_name}\n"
    if contact_info:
        kit += f"招标方联系人：{contact_info}\n"
    kit += f"核心问题：请问是否接受联合体投标？\n"
    kit += f"接听人：______\n"
    kit += f"答复：□ 接受  □ 不接受\n"
    kit += f"具体要求：______\n"
    kit += f"记录人签字：______\n"
    kit += "```\n"
    
    return kit