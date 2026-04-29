# stream_handler.py
"""
流式输出组件
- 打字机效果展示 AI 分析进度
- 同时保留完整结果用于后续处理
"""
import streamlit as st
import time
from typing import Generator


class StreamDisplay:
    """流式输出显示器"""
    
    def __init__(self, placeholder_label: str = "🤖 AI 正在分析..."):
        self.status = st.empty()
        self.progress = st.empty()
        
    def show_progress(self, stage: str):
        """显示当前阶段"""
        self.status.info(f"⏳ {stage}")
    
    def stream_text(self, text_generator: Generator[str, None, None], stage_name: str):
        """
        逐字显示文本
        参数：
        - text_generator: 生成文本的生成器
        - stage_name: 阶段名称（如"提取标书要求"）
        """
        full_text = ""
        text_placeholder = st.empty()
        
        for chunk in text_generator:
            full_text += chunk
            # 显示打字机效果
            text_placeholder.markdown(
                f"### 📝 {stage_name}\n\n{full_text}▌"
            )
            time.sleep(0.02)  # 控制打字速度
        
        # 完成后去掉光标
        text_placeholder.markdown(
            f"### ✅ {stage_name}\n\n{full_text}"
        )
        
        return full_text
    
    def stream_json(self, json_data: dict, stage_name: str):
        """流式显示JSON（逐个字段展示）"""
        import json
        
        text_placeholder = st.empty()
        keys = list(json_data.keys())
        shown = {}
        
        for i, key in enumerate(keys):
            shown[key] = json_data[key]
            # 格式化显示
            display_text = json.dumps(shown, ensure_ascii=False, indent=2)
            text_placeholder.code(
                f"### 📝 {stage_name} ({i+1}/{len(keys)})\n\n{display_text}",
                language="json"
            )
            time.sleep(0.3)  # 字段逐个出现
        
        text_placeholder.code(
            f"### ✅ {stage_name}\n\n{json.dumps(json_data, ensure_ascii=False, indent=2)}",
            language="json"
        )
        
        return json_data
    
    def clear(self):
        """清除显示"""
        self.status.empty()
        self.progress.empty()


def simulate_ai_stream(text: str, chunk_size: int = 3) -> Generator[str, None, None]:
    """
    模拟AI流式输出
    实际使用时替换为真实的流式API调用
    """
    for i in range(0, len(text), chunk_size):
        yield text[i:i+chunk_size]
        
def show_ai_progress(stage: str):
    """在页面上显示进度提示"""
    placeholder = st.empty()
    placeholder.info(f"⏳ {stage}...")
    return placeholder


def show_result_preview(data: dict, title: str):
    """以动画效果展示提取结果"""
    placeholder = st.empty()
    placeholder.info(f"📝 {title} - 正在整理结果...")
    time.sleep(0.3)
    
    items = list(data.items()) if isinstance(data, dict) else []
    for i, (key, value) in enumerate(items):
        if isinstance(value, list):
            v_str = "、".join(str(v) for v in value) if value else "无"
        elif value is None or str(value).strip() == "":
            v_str = "未提取到"
        else:
            v_str = str(value)[:100]
        
        final_lines = [f"### ✅ {title}"]
        for k, v in items[:i+1]:
            if isinstance(v, list):
                s = "、".join(str(x) for x in v) if v else "无"
            elif v is None or str(v).strip() == "":
                s = "未提取到"
            else:
                s = str(v)[:100]
            final_lines.append(f"- **{k}**：{s}")
        
        placeholder.markdown("\n".join(final_lines))
        time.sleep(0.15)
    
    return placeholder        