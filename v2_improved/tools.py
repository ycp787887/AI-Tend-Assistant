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
    
    prompt = f"""判断用户意图，只回复一个词。

优先级规则：
- 如果用户提到了具体平台名称（广联达、政采云、新点、筑龙、齐鲁云采等），优先判断为 platform_guide
- 如果用户问的是文件打不开、什么格式、怎么解析（且没有提具体平台），判断为 file_diagnose

意图列表：
- platform_guide：询问某个平台如何下载标书、操作步骤、怎么打开从该平台下载的文件
- file_diagnose：询问文件打不开、什么格式、怎么解析，但没有指定是哪个平台
- deadline：询问投标截止时间或剩余天数
- cert：询问某个具体资质证书的办理要求
- partner：询问如何找联合体合作伙伴
- launch_tool：用户要求打开、启动、运行某个标书制作工具或软件（如"帮我打开新点""启动广联达"）
- prebid_checklist：用户在投标前想检查材料是否齐全、需要准备什么、资格审查、查漏补缺（如"我需要准备哪些材料""帮我检查标书""投标前要做哪些准备"）
- chat：其他问题

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

def extract_platform_name(user_input: str) -> str:
    """从用户输入中提取平台名称"""
    known_platforms = ["广联达", "政采云", "新点", "筑龙", "齐鲁云采", "国泰新点", "公共资源交易中心"]
    for platform in known_platforms:
        if platform in user_input:
            return platform
    return user_input  # 没匹配到就把整句话传进去，get_platform_guide 会返回通用指引



def try_handle_with_tool(user_input: str, core: dict, api_key: str) -> str | None:
    """尝试用工具处理用户输入，如果能处理则返回结果，否则返回None"""
    
    # 1. 文件诊断类问题（不依赖具体平台）
    if "打不开" in user_input or "什么格式" in user_input or "怎么解析" in user_input:
        # 检查是否提到了特定平台
        platforms = ["广联达", "政采云", "新点", "筑龙", "齐鲁云采"]
        for platform in platforms:
            if platform in user_input:
                return get_platform_guide(platform)
        
        # 检查.sdtf等特殊格式
        if ".sdtf" in user_input.lower():
            return """`.sdtf` 是部分地区公共资源交易平台的专用标书格式，无法直接用普通软件打开。

**正确操作指引：**
1. 访问对应平台的官方网站（如当地公共资源交易中心）
2. 下载该平台的「投标文件制作工具」
3. 安装后用该工具打开 `.sdtf` 文件

⚠️ 请不要尝试用文本编辑器或PDF阅读器打开，这会导致文件损坏。"""
        
        # 通用文件诊断
        return """请提供更多信息以便诊断：
1. 文件的后缀名是什么？（.pdf/.sdtf/.zip等）
2. 打开时提示什么错误？
3. 文件是从哪个平台下载的？
4. 如果您需要某个平台的操作指引，请告诉我平台名称（如广联达、政采云等）。"""
    
    # 2. 平台指引类问题
    platforms = ["广联达", "政采云", "新点", "筑龙", "齐鲁云采", "国泰新点"]
    for platform in platforms:
        if platform in user_input:
            return get_platform_guide(platform)
    
    # 3. 启动工具类
    if "打开" in user_input and any(p in user_input for p in platforms):
        for platform in platforms:
            if platform in user_input:
                return f"""请手动启动 {platform} 投标工具：
1. 在桌面或开始菜单找到「{platform}投标文件制作工具」
2. 双击运行
3. 在工具内选择「导入」-> 选择您的标书文件

如果未安装，请访问{platform}官网下载安装包。"""
    
    # 无法处理，返回None让其他逻辑处理
    return None


def get_platform_guide(platform: str) -> str:
    """获取平台操作指引"""
    guides = {
        "广联达": """【广联达操作指引】
1. 下载：访问广联达G+工作台，下载「投标文件编制工具」
2. 打开标书：打开工具 → 点击「新建/导入」→ 选择.招标文件或.投标文件
3. 注意事项：首次使用需安装加密锁驱动，插入CA锁后操作""",
        
        "政采云": """【政采云操作指引】
1. 登录政采云平台（www.zcygov.cn）
2. 进入「项目采购」→「获取采购文件」
3. 下载的如果是加密文件，需使用「政采云投标客户端」打开
4. 客户端下载：平台首页 → 帮助中心 → 下载专区 → 投标客户端""",
        
        "新点": """【新点操作指引】
1. 访问当地公共资源交易中心网站
2. 在「下载中心」找到「新点投标文件制作软件」
3. 安装后用软件打开.招标文件或.XJZF文件
4. 如遇问题，拨打新点客服：400-850-3300""",
        
        "筑龙": """【筑龙操作指引】
1. 访问筑龙电子招投标平台
2. 下载「筑龙投标文件制作工具」
3. 用CA锁登录工具，导入招标文件
4. 如遇到.sdtf格式，需使用对应平台的定制版本""",
    }
    
    for key, guide in guides.items():
        if key in platform:
            return guide
    
    return f"""【{platform}操作指引】
1. 访问{platform}官方网站或对应的公共资源交易平台
2. 在「下载中心」或「服务支持」找到投标文件制作工具
3. 下载并安装后，用工具打开标书文件
4. 如遇到问题，建议联系平台客服或查看官方帮助文档"""



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

# tools.py 新增部分

def get_platform_guide(platform_name: str) -> str:
    """根据平台名称，返回标书下载操作指引"""
    guides = {
        "广联达": (
            "📦 **广联达平台操作指引**\n"
            "1. 使用CA数字证书登录广联达电子交易平台\n"
            "2. 进入【项目采购】→【获取采购文件】\n"
            "3. 找到对应项目，点击下载招标文件\n"
            "4. 文件格式通常为 .gld / .gcf，需用广联达GCCP软件打开\n"
            "5. 打开后可通过软件导出为PDF，再上传到本系统分析"
        ),
        "政采云": (
            "☁️ **政采云平台操作指引**\n"
            "1. 登录政采云平台（zfcg.gov.cn）\n"
            "2. 进入【项目采购】→【采购文件获取】\n"
            "3. 申请获取采购文件，等待审核通过\n"
            "4. 审核通过后下载专属标书文件（PDF或平台专用格式）\n"
            "5. 注意：非经此路径获取的标书，开标时可能按无效投标处理"
        ),
        "新点": (
            "📦 **新点电子交易平台操作指引**\n"
            "1. 使用CA锁登录新点平台\n"
            "2. 找到对应项目，点击【下载招标文件】\n"
            "3. 文件格式可能为 .sdtf / .sxstf，需用新点标书制作工具打开\n"
            "4. 通过标书制作工具可查看完整内容，并导出为PDF"
        ),
        "筑龙": (
            "📦 **筑龙电子招标平台操作指引**\n"
            "1. 使用CA锁登录筑龙平台\n"
            "2. 在项目列表中找到对应标段\n"
            "3. 下载招标文件（格式可能为 .hyzf 或 .pdf）\n"
            "4. 如为 .hyzf 格式，需用筑龙标书工具打开"
        ),
    }
    
    platform_lower = platform_name.lower()
    for key, guide in guides.items():
        if key in platform_lower or platform_lower in key:
            return guide
    
    return (
        f"📂 **关于「{platform_name}」平台**\n"
        f"建议按以下通用步骤操作：\n"
        f"1. 确认该平台的官方网址和登录方式\n"
        f"2. 使用CA数字证书或账号密码登录\n"
        f"3. 在【项目采购】或【招标文件获取】栏目找到对应项目\n"
        f"4. 下载招标文件（注意文件格式）\n"
        f"5. 如为专用格式，使用对应标书制作工具打开后导出PDF\n"
        f"6. 将PDF上传到本系统进行分析"
    )


def diagnose_file_issue(user_description: str) -> str:
    """根据用户描述，诊断文件问题并给出建议"""
    desc_lower = user_description.lower()
    
    # === 1. 先匹配专用格式（优先级最高） ===
    if any(kw in desc_lower for kw in ["sdtf", "sxstf", "hyzf", "gld", "gcf", "zyhbzf", "lycgzf", "专用格式"]):
        return (
            "📦 **诊断：电子交易平台专用格式**\n"
            "此类文件需要平台专用工具才能打开。\n"
            "请告诉我您使用的是哪个平台（如广联达、新点、筑龙），"
            "我可以提供详细的操作指引。"
        )
    
    # === 2. 加密文件 ===
    if any(kw in desc_lower for kw in ["密码", "加密", "encrypt"]):
        return (
            "🔒 **诊断：文件已加密**\n"
            "请上传加密文件到本系统，我可以帮您：\n"
            "1. 尝试自动移除权限限制\n"
            "2. 如果您知道密码，输入密码解锁\n"
            "请在侧边栏选择「📄 我已经有标书文件了」并上传该加密PDF。"
        )
    
    # === 3. 扫描件/图片 ===
    if any(kw in desc_lower for kw in ["扫描件", "图片", "拍照", "纸质"]):
        return (
            "📷 **诊断：文件为扫描件/图片型PDF**\n"
            "本系统支持OCR识别扫描件文字。\n"
            "请上传该文件，系统会自动检测并启动OCR处理。"
        )
    
    # === 4. 压缩包 ===
    if any(kw in desc_lower for kw in ["zip", "rar", "压缩包", "解压"]):
        return (
            "📦 **诊断：压缩包文件**\n"
            "请在首页选择「📄 我已经有标书文件了」，上传压缩包。\n"
            "系统会自动解压并提取其中的PDF文件进行分析。"
        )
    
    # === 5. 打不开（兜底） ===
    if any(kw in desc_lower for kw in ["打不开", "怎么看", "什么格式", "怎么打开", "解析"]):
        return (
            "🤔 **无法确定文件问题**\n"
            "请更详细地描述：\n"
            "- 文件的后缀名是什么？（.pdf / .sdtf / .zip 等）\n"
            "- 打开时提示什么错误？\n"
            "- 文件是从哪里下载的？"
        )
    
    return (
        "🤔 **无法确定文件问题**\n"
        "请更详细地描述您遇到的情况。"
    )


def launch_local_tool(platform_name: str) -> str:
    """
    生成打开本地标书制作工具的命令和详细操作指引。
    注意：网页Agent无法直接操控用户桌面，此处提供最接近“代劳”的体验。
    """
    import shutil

    tool_map = {
        "新点": {
            "executable": "EpointBidMaker.exe",
            "find_cmd": 'where EpointBidMaker.exe',
            "manual_path": r"C:\Program Files\Epoint\BidMaker\EpointBidMaker.exe",
            "steps": [
                "1. 按 Win 键，输入 EpointBidMaker 搜索",
                "2. 右键图标 → 以管理员身份运行",
                "3. 在软件中点击【打开文件】，选择你的 .sdtf 文件"
            ]
        },
        "广联达": {
            "executable": "GCCP.exe",
            "find_cmd": 'where GCCP.exe',
            "manual_path": r"C:\Program Files\Glodon\GCCP\GCCP.exe",
            "steps": [
                "1. 按 Win 键，输入 GCCP 搜索",
                "2. 右键图标 → 以管理员身份运行",
                "3. 在软件中点击【打开项目】，选择你的 .gld 文件"
            ]
        },
        "筑龙": {
            "executable": "ZhuLongBid.exe",
            "find_cmd": 'where ZhuLongBid.exe',
            "manual_path": r"C:\Program Files\ZhuLong\BidTool\ZhuLongBid.exe",
            "steps": [
                "1. 按 Win 键，输入 ZhuLongBid 搜索",
                "2. 右键图标 → 以管理员身份运行",
                "3. 在软件中点击【打开文件】，选择你的 .hyzf 文件"
            ]
        }
    }

    platform_lower = platform_name.lower()
    for key, info in tool_map.items():
        if key in platform_lower or platform_lower in key:
            exe = info["executable"]
            find = info["find_cmd"]
            manual = info["manual_path"]
            steps = "\n".join(info["steps"])

            # 检查本地是否安装
            if shutil.which(exe):
                return (
                    f"✅ **已检测到 {key} 标书制作工具已安装。**\n\n"
                    f"🔧 **我已为您准备好启动命令（请复制到终端运行）：**\n"
                    f"```cmd\nstart {exe}\n```\n\n"
                    f"📋 **或按以下步骤手动操作：**\n{steps}\n\n"
                    f"💡 💡 软件启动后，请用它打开您的专用格式文件，然后导出为PDF。导出后，请在本页面选择「📄 我已经有标书文件了，需要分析」，上传该PDF，系统将自动进行资质匹配、废标风险检查和合规分析。"
                )
            else:
                return (
                    f"⚠️ **未检测到 {key} 标书制作工具。**\n\n"
                    f"📂 默认安装路径：`{manual}`\n"
                    f"🔍 如果已安装但未检测到，请运行以下命令查找：\n"
                    f"```cmd\n{find}\n```\n\n"
                    f"📋 **如已确认安装，请按以下步骤手动操作：**\n{steps}\n\n"
                    f"💡 💡 如未安装，请联系平台技术支持获取安装包。安装完成后，请用该工具打开您的专用格式文件并导出为PDF。导出后，请在本页面选择「📄 我已经有标书文件了，需要分析」，上传该PDF，系统将自动进行资质匹配、废标风险检查和合规分析。"
                )

    return (
        f"❌ 未识别平台「{platform_name}」的专用工具。\n"
        f"请手动启动对应标书制作软件，打开文件后导出为PDF。"
    )


def generate_prebid_checklist(user_input: str) -> str:
    """
    根据用户描述的平台和项目类型，生成投标准备检查清单。
    目前基于规则匹配，后续可接入各平台官方要求。
    """
    input_lower = user_input.lower()
    
    # 识别平台
    platform = None
    for p in ["新点", "广联达", "政采云", "筑龙", "齐鲁云采"]:
        if p in user_input:
            platform = p
            break
    
    # 识别项目类型
    project_type = "通用"
    if any(kw in input_lower for kw in ["施工", "工程", "建筑", "土建"]):
        project_type = "施工类"
    elif any(kw in input_lower for kw in ["监理"]):
        project_type = "监理类"
    elif any(kw in input_lower for kw in ["货物", "设备", "采购"]):
        project_type = "货物类"
    elif any(kw in input_lower for kw in ["服务", "咨询", "设计"]):
        project_type = "服务类"
    
    # 通用检查清单
    common_items = [
        ("营业执照副本", "是否在有效期内？是否已年检？"),
        ("法定代表人身份证", "正反面是否清晰？"),
        ("授权委托书", "如需代理人投标，是否已准备？被授权人身份证是否在有效期内？"),
        ("资质证书", "是否满足标书要求的资质等级？是否在有效期内？"),
        ("财务审计报告", "是否满足标书要求的年限（如近三年）？是否由合规的会计师事务所出具？"),
        ("纳税证明", "是否满足标书要求的连续纳税年限？"),
        ("社保缴纳证明", "是否满足标书要求的连续缴纳年限？"),
        ("无重大违法记录声明", "是否已准备？格式是否符合标书要求？"),
        ("投标保证金", "是否已按标书要求金额缴纳？是否已到账？缴款凭证是否已保留？"),
        ("CA数字证书", "是否在有效期内？驱动是否已安装？密码是否牢记？"),
    ]
    
    # 平台特定提醒
    platform_reminders = {
        "新点": [
            ("投标文件制作软件", "请确认已安装最新版新点投标文件制作工具，注意查看软件版本是否与标书要求一致"),
            ("CA锁检测", "插入CA锁后，打开软件，点击【检测CA锁】，确认证书信息与投标单位一致"),
            ("投标文件生成", "所有材料导入完成后，点击【生成投标文件】，注意选择正确的加密方式和签章位置"),
        ],
        "广联达": [
            ("GCCP软件版本", "请确认GCCP版本与招标文件要求一致（通常标书会注明最低版本号）"),
            ("清单文件", "请确认已下载完整的工程量清单文件（.gld/.gcf），并能在GCCP中正常打开"),
            ("组价文件导出", "完成组价后，导出为平台要求的投标报价文件格式"),
        ],
        "政采云": [
            ("供应商资格确认", "请确认已在政采云平台完成供应商注册，且状态为'正常'"),
            ("电子签章", "请确认电子签章已完成年检，且在有效期内"),
            ("投标文件上传", "请确认在投标截止时间前，已成功上传所有投标文件，并收到平台确认回执"),
        ],
        "筑龙": [
            ("筑龙投标工具", "请确认已安装最新版筑龙投标文件制作工具"),
            ("文件格式兼容", "请确认所有导入文件格式（Word/Excel/PDF）与筑龙工具兼容"),
            ("签章校验", "生成投标文件后，使用工具内的【校验】功能，确保签章和格式无误"),
        ],
    }
    
    # 生成输出
    output = f"## 📋 投标准备检查清单\n\n"
    
    if platform:
        output += f"**目标平台：{platform}**"
    else:
        output += "**目标平台：未指定（请在后续告诉我平台名称，可补充平台特定检查项）**"
    
    output += f"  |  **项目类型：{project_type}**\n\n"
    output += "---\n\n"
    
    output += "### 一、通用资质与文件\n\n"
    output += "| 序号 | 检查项 | 自检问题 | 状态 |\n"
    output += "|------|--------|----------|------|\n"
    for i, (item, question) in enumerate(common_items, 1):
        output += f"| {i} | {item} | {question} | ⬜ 待检查 |\n"
    
    if platform and platform in platform_reminders:
        output += f"\n### 二、{platform}平台专项检查\n\n"
        output += "| 序号 | 检查项 | 说明 | 状态 |\n"
        output += "|------|--------|------|------|\n"
        for i, (item, desc) in enumerate(platform_reminders[platform], 1):
            output += f"| {i} | {item} | {desc} | ⬜ 待检查 |\n"
    
    output += "\n### 三、时间节点提醒\n\n"
    output += "- ⏰ 请确认投标截止时间，建议至少提前2个工作日完成所有材料准备\n"
    output += "- ⏰ 如对招标文件有疑问，请在澄清截止时间前提交书面质疑\n"
    output += "- ⏰ 投标保证金如通过电汇，请预留到账时间（通常1-2个工作日）\n"
    
    output += "\n---\n"
    output += "💡 **使用建议**：请逐项核对，勾选已确认项。完成后回复「我准备好了」，或告诉我需要深入指导的具体项目序号。"
    
    return output



# 更新 TOOL_ROUTER
TOOL_ROUTER["platform_guide"] = {
    "keywords": ["平台", "下载", "怎么获取", "操作指引", "广联达", "政采云", "新点", "筑龙"],
    "handler": get_platform_guide,
    "data_key": None
}
TOOL_ROUTER["file_diagnose"] = {
    "keywords": ["打不开", "怎么看", "什么格式", "怎么打开", "解析"],
    "handler": diagnose_file_issue,
    "data_key": None
}

TOOL_ROUTER["launch_tool"] = {
    "keywords": ["打开工具", "启动", "帮我打开", "打开软件", "启动软件", "运行工具"],
    "handler": launch_local_tool,
    "data_key": None
}
TOOL_ROUTER["prebid_checklist"] = {
    "keywords": ["准备投标", "检查清单", "需要什么材料", "怎么准备", "投标材料", "资格审查", "查漏补缺", "标书检查", "资料清单"],
    "handler": generate_prebid_checklist,
    "data_key": None
}


