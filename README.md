# 投标文件合规预审助手

AI 驱动的投标文件自动比对工具。

## 版本说明

### v1_original - 原始版本
- 单文件实现，最小可用原型
- 运行：`cd v1_original && streamlit run app.py`

### v2_improved - 健壮化版本
- 模块化架构（9个模块）
- 磁盘缓存（避免重复API调用）
- 指数退避重试机制
- 优雅降级（AI不可用时正则兜底）
- 运行：`cd v2_improved && streamlit run main.py`

## 快速开始

```bash
# 1. 克隆仓库
git clone https://github.com/你的用户名/仓库名.git
cd 仓库名

# 2. 安装依赖
pip install -r v2_improved/requirements.txt

# 3. 配置 API Key
cp .env.example .env
# 编辑 .env，填入你的 DeepSeek API Key

# 4. 运行
cd v2_improved
streamlit run main.py

技术栈

Streamlit

DeepSeek API

python-dotenv