# ocr_utils.py
# 把扫描件PDF/图片变成文字

import pytesseract
from pdf2image import convert_from_bytes
from PIL import Image
from io import BytesIO

# Windows 需要指定 tesseract 路径（改成你的实际安装路径）
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

# Windows 需要指定 poppler 路径（改成你的实际解压路径）
POPPLER_PATH = r'C:\Program Files\poppler-26.02.0\Library\bin'


def ocr_pdf(file_bytes: bytes) -> str:
    """
    对扫描件 PDF 进行 OCR 识别
    输入：PDF 文件的字节流
    输出：识别出的文字
    """
    # 第一步：把 PDF 每一页转成图片
    images = convert_from_bytes(file_bytes, dpi=200, poppler_path=POPPLER_PATH)
    
    # 第二步：对每一页图片进行 OCR 识别
    all_text = []
    for i, img in enumerate(images):
        # tesseract 识别图片中的文字，chi_sim=简体中文，eng=英文
        page_text = pytesseract.image_to_string(img, lang='chi_sim+eng')
        all_text.append(f"--- 第 {i+1} 页 ---\n{page_text}")
    
    return "\n".join(all_text)


def ocr_image(file_bytes: bytes) -> str:
    """
    对单张图片进行 OCR 识别
    输入：图片文件的字节流（png/jpg/jpeg）
    输出：识别出的文字
    """
    img = Image.open(BytesIO(file_bytes))
    text = pytesseract.image_to_string(img, lang='chi_sim+eng')
    return text