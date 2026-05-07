# text_splitter.py
"""
文档切分模块
把长文本切成小段落，每段约500字
"""
from langchain_text_splitters import RecursiveCharacterTextSplitter


def split_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    """
    把文本切成小段
    chunk_size: 每段最大字数
    overlap: 段与段之间重叠字数（防止关键信息被切断）
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=overlap,
        separators=["\n\n", "\n", "。", ".", " "]
    )
    return splitter.split_text(text)