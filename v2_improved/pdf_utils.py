# pdf_utils.py
# 这个文件只做一件事：把PDF文件变成文字
# 如果PDF解析出问题，来这里改

from io import BytesIO
from pypdf import PdfReader

def extract_pdf_text(file_bytes: bytes) -> str:
    """
    从PDF字节流中提取纯文本
    输入：PDF文件的二进制内容
    输出：提取出的文字
    """
    reader = PdfReader(BytesIO(file_bytes))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n".join(pages)