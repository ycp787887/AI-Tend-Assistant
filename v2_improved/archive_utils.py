# archive_utils.py
import zipfile
import tempfile
import os
from io import BytesIO
from pathlib import Path

def extract_archive(file_bytes: bytes, filename: str = "") -> dict:
    """
    解压 ZIP/RAR 压缩包，返回文件名到字节流的字典
    支持 ZIP，RAR 需要额外安装 unrar 工具
    """
    result = {}
    suffix = filename.split('.')[-1].lower() if '.' in filename else ''
    
    # ZIP 处理
    if suffix == 'zip':
        with zipfile.ZipFile(BytesIO(file_bytes)) as zf:
            for name in zf.namelist():
                if name.endswith('/'):  # 跳过文件夹
                    continue
                result[name] = zf.read(name)
        return result
    
    # RAR 处理（需要系统安装了 unrar 或 unrar-free）
    if suffix == 'rar':
        try:
            import subprocess
            with tempfile.NamedTemporaryFile(suffix='.rar', delete=False) as tmp:
                tmp.write(file_bytes)
                tmp_path = tmp.name
            
            extract_dir = tempfile.mkdtemp()
            subprocess.run(['unrar', 'x', '-y', tmp_path, extract_dir], 
                         capture_output=True, check=True, timeout=60)
            
            for root, _, files in os.walk(extract_dir):
                for f in files:
                    fpath = os.path.join(root, f)
                    relpath = os.path.relpath(fpath, extract_dir)
                    with open(fpath, 'rb') as fobj:
                        result[relpath] = fobj.read()
            
            os.unlink(tmp_path)
            return result
        except FileNotFoundError:
            raise RuntimeError("未安装 unrar 工具，无法解压 RAR 文件")
    
    return {}