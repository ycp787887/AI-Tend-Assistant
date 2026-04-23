# retry_handler.py
"""
API 调用重试机制
- 指数退避：1秒 → 2秒 → 4秒
- 最大重试 3 次
- 检查异常类型名字（不依赖异常消息）
"""
import time
import functools
import logging
from typing import Callable, Any

MAX_RETRIES = 3
BASE_DELAY = 1
MAX_DELAY = 30

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

retry_messages = []


def _should_retry(exception: Exception) -> bool:
    """判断是否应该重试"""
    exc_name = type(exception).__name__.lower()
    exc_str = str(exception).lower()
    
    # 致命错误类名（直接放弃）
    fatal_names = [
        "authenticationerror",      # 401 认证失败
        "permissiondeniederror",    # 403 无权限
        "invalidrequesterror",      # 请求无效
    ]
    
    # 可重试错误类名
    retry_names = [
        "apiconnectionerror",       # 网络断开
        "apitimeouterror",          # 超时
        "ratelimiterror",           # 频率限制
        "internalservererror",      # 500 服务器错误
        "serviceunavailableerror",  # 503 服务不可用
    ]
    
    # 检查类名
    for name in fatal_names:
        if name in exc_name:
            return False
    
    for name in retry_names:
        if name in exc_name:
            return True
    
    # 兜底：检查错误消息
    if any(kw in exc_str for kw in ["timeout", "connection", "rate limit", "503", "502", "429"]):
        return True
    
    if any(kw in exc_str for kw in ["401", "403", "authentication", "invalid api key"]):
        return False
    
    return False


def with_retry(func: Callable) -> Callable:
    @functools.wraps(func)
    def wrapper(*args, **kwargs) -> Any:
        global retry_messages
        retry_messages = []
        last_exception = None
        
        for attempt in range(MAX_RETRIES + 1):
            try:
                result = func(*args, **kwargs)
                if attempt > 0:
                    logger.info(f"✅ 第{attempt+1}次尝试成功")
                return result
                
            except Exception as e:
                last_exception = e
                
                if _should_retry(e) and attempt < MAX_RETRIES:
                    wait_time = min(BASE_DELAY * (2 ** attempt), MAX_DELAY)
                    msg = f"⚠️ 调用失败，{wait_time}秒后重试（第{attempt+1}/{MAX_RETRIES}次）"
                    retry_messages.append(msg)
                    logger.info(msg)
                    time.sleep(wait_time)
                    continue
                else:
                    logger.error(f"❌ 放弃: {type(e).__name__}")
                    raise
        
        raise last_exception
    
    return wrapper


def get_retry_messages():
    return retry_messages