# logger_config.py
"""
日志系统配置
- 同时输出到终端和 app.log 文件
- 每天自动切割日志文件
- 防止重复添加 handler
"""
import logging
import sys
from pathlib import Path
from datetime import datetime

# 日志目录
LOG_DIR = Path("./logs")
LOG_DIR.mkdir(exist_ok=True)

# 日志文件名（按日期）
log_filename = LOG_DIR / f"app_{datetime.now().strftime('%Y%m%d')}.log"

# 日志格式
log_format = logging.Formatter(
    "%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S"
)


def setup_logger():
    """创建 logger（防止重复）"""
    logger = logging.getLogger("bid_checker")
    
    # ⭐ 关键：如果已经有 handler，直接返回
    if logger.handlers:
        return logger
    
    logger.setLevel(logging.DEBUG)
    
    # 文件输出
    file_handler = logging.FileHandler(log_filename, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(log_format)
    logger.addHandler(file_handler)
    
    # 终端输出
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(log_format)
    logger.addHandler(console_handler)
    
    return logger


# 初始化
logger = setup_logger()
logger.info("=" * 40)
logger.info("投标文件合规预审助手 启动")
logger.info(f"日志文件: {log_filename}")