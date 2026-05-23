# pdf_unlocker.py
# 文档解密与修复工具 —— “开锁匠”
# 处理有密码、有证书限制、有编辑限制的PDF

import subprocess
import tempfile
import os
from io import BytesIO
from pathlib import Path

def try_remove_password(file_bytes: bytes, password: str) -> bytes:
    """
    尝试用用户提供的密码解锁PDF
    使用 pikepdf 库，可以移除打开密码
    """
    try:
        import pikepdf
        pdf = pikepdf.open(BytesIO(file_bytes), password=password)
        output = BytesIO()
        pdf.save(output)
        pdf.close()
        return output.getvalue()
    except ImportError:
        raise RuntimeError("pikepdf 未安装，请运行 pip install pikepdf")
    except pikepdf.PasswordError:
        raise ValueError("密码错误，请重新输入")
    except Exception as e:
        raise RuntimeError(f"解锁失败: {str(e)[:100]}")


def try_remove_restrictions(file_bytes: bytes) -> bytes:
    """
    尝试移除PDF的权限限制（如禁止打印、禁止复制等）
    使用 qpdf 命令行工具。
    Windows 兼容版：优先使用完整路径调用 qpdf.exe
    """
    import subprocess
    import tempfile
    import os

    # 1. 写入临时文件
    with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp_in:
        tmp_in.write(file_bytes)
        tmp_in_path = tmp_in.name

    tmp_out_path = tmp_in_path.replace('.pdf', '_unlocked.pdf')

    try:
        # 2. 查找 qpdf 可执行文件
        qpdf_path = shutil.which('qpdf')
        if not qpdf_path:
            # 常见安装位置，按需修改
            possible_paths = [
                r'C:\tools\qpdf\qpdf-12.3.2\bin\qpdf.exe',
                r'C:\Program Files\qpdf\bin\qpdf.exe',
                r'C:\qpdf\bin\qpdf.exe',
            ]
            for p in possible_paths:
                if os.path.exists(p):
                    qpdf_path = p
                    break
        
        if not qpdf_path:
            raise RuntimeError(
                "未找到 qpdf 命令行工具。\n"
                "安装方法：\n"
                "1. 下载 qpdf 免安装包\n"
                "2. 解压到 C:\\tools\\qpdf\n"
                "3. 将 bin 目录加入系统环境变量 PATH"
            )

        # 3. 执行解密
        result = subprocess.run(
            [qpdf_path, '--decrypt', tmp_in_path, tmp_out_path],
            capture_output=True,
            text=True,
            timeout=30,
            shell=True  # Windows 下有时需要这个
        )

        if result.returncode != 0:
            raise RuntimeError(f"qpdf 执行失败: {result.stderr[:200]}")

        # 4. 读取解密后的文件
        with open(tmp_out_path, 'rb') as f:
            unlocked_bytes = f.read()

        return unlocked_bytes

    finally:
        # 5. 清理临时文件（无论成功与否）
        for p in [tmp_in_path, tmp_out_path]:
            if os.path.exists(p):
                try:
                    os.unlink(p)
                except:
                    pass


def attempt_auto_unlock(file_bytes: bytes) -> tuple[bytes, str]:
    """
    自动尝试解锁PDF（不需要密码的情况）
    返回 (解锁后的文件字节流, 使用的解锁方式)
    
    解锁方式包括:
    - 'direct': 文件本来就没有加密限制
    - 'qpdf': 通过 qpdf 移除了权限限制
    - 'failed': 所有自动方法都失败了，需要用户输入密码
    """
    # 先检查是不是真的需要处理
    try:
        from pypdf import PdfReader
        reader = PdfReader(BytesIO(file_bytes))
        
        # 如果文件没有加密标记，直接返回
        if not reader.is_encrypted:
            return file_bytes, 'direct'
    except:
        pass
    
    # 尝试1: 用 qpdf 解除权限限制（不需要密码的那种加密通常能搞定）
    try:
        unlocked = try_remove_restrictions(file_bytes)
        # 验证解锁后能正常读取
        from pypdf import PdfReader
        reader = PdfReader(BytesIO(unlocked))
        if not reader.is_encrypted:
            return unlocked, 'qpdf'
    except:
        pass
    
    # 所有自动方法失败，需要用户给密码
    return file_bytes, 'failed'