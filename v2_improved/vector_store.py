# vector_store.py
"""
向量检索模块
1. 把段落变成向量存起来
2. 根据查询找最相关的段落
"""
import chromadb
from chromadb.config import Settings
from text_splitter import split_text


# 全局客户端（只初始化一次）
_client = None
_collection = None


def _get_collection():
    """获取或创建 ChromaDB 集合"""
    global _client, _collection
    if _collection is None:
        _client = chromadb.Client(Settings(anonymized_telemetry=False))
        _collection = _client.get_or_create_collection("tender_docs")
    return _collection


def build_index(text: str):
    """
    为标书建立索引
    - 切分文本
    - 每段存入向量数据库
    """
    collection = _get_collection()
    
    # 清空旧索引
    try:
        collection.delete(ids=collection.get()["ids"])
    except:
        pass
    
    # 切分文本
    chunks = split_text(text)
    
    if not chunks:
        return
    
    # 存入数据库
    collection.add(
        documents=chunks,
        ids=[f"chunk_{i}" for i in range(len(chunks))]
    )
    
    return len(chunks)


def search_relevant(text: str, query: str, top_k: int = 5) -> list[str]:
    """
    搜索和查询最相关的段落
    - query: 搜索关键词
    - top_k: 返回最相关的几段
    - 返回: 段落文本列表
    """
    # 先建索引
    build_index(text)
    
    collection = _get_collection()
    
    # 搜索
    results = collection.query(
        query_texts=[query],
        n_results=min(top_k, len(collection.get()["ids"]))
    )
    
    if results["documents"] and results["documents"][0]:
        return results["documents"][0]
    
    # 降级：返回前5000字
    return [text[:5000]]