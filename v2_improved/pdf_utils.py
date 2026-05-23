# pdf_utils.py
# 这个文件只做一件事：把PDF文件变成文字
# 如果PDF解析出问题，来这里改

from io import BytesIO
from pypdf import PdfReader

def extract_pdf_text(file_bytes: bytes) -> str:
    """
    从PDF字节流中提取纯文本
    输入：PDF文件的二进制内容 或 OCR后的纯文本字节流
    输出：提取出的文字
    """
    # ===== 防线0：如果是OCR后的纯文本，直接返回 =====
    if file_bytes[:4] != b'%PDF':
        try:
            return file_bytes.decode('utf-8')
        except:
            raise ValueError("无法识别文件内容，请确认文件格式")
    
    # ===== 防线1：文件头校验 =====
    if not file_bytes[:5].startswith(b'%PDF-'):
        raise ValueError("不是有效的PDF文件（文件头不匹配）")
    
    # ===== 防线2：正常解析 =====
    reader = PdfReader(BytesIO(file_bytes))
    
    # ===== 防线3：检查是否是加密文件 =====
    if reader.is_encrypted:
        raise PermissionError("PDF文件已加密，需要密码才能读取")
    
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n".join(pages)