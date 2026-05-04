# history_db.py
"""
历史记录存储 - SQLite
- 每次分析完成后自动保存
- 支持按时间查看、删除
"""
import sqlite3
import json
from datetime import datetime
from pathlib import Path

DB_PATH = Path("./history.db")


def init_db():
    """初始化数据库（首次运行时自动创建）"""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            tender_name TEXT,
            company_count INTEGER,
            results_json TEXT NOT NULL,
            best_company TEXT
        )
    """)
    conn.commit()
    conn.close()


def save_analysis(tender_name: str, all_results: list, best_company: str,hidden_risks: list = None,core: dict = None):
    """保存一次分析记录"""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO history (created_at, tender_name, company_count, results_json, best_company) VALUES (?, ?, ?, ?, ?)",
        (
            datetime.now().strftime("%Y-%m-%d %H:%M"),
            tender_name or "未命名标书",
            len(all_results),
            json.dumps({
                "all_results": all_results,
                "hidden_risks": hidden_risks or [],  # ← 多存一个字段
                "core": core or {}  # ← 多存标书信息
            }, ensure_ascii=False),
            best_company
        )
    )
    conn.commit()
    conn.close()


def get_all_history():
    """获取所有历史记录（按时间倒序）"""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT id, created_at, tender_name, company_count, best_company FROM history ORDER BY id DESC LIMIT 50"
    ).fetchall()
    conn.close()
    return rows


def get_history_detail(history_id: int):
    """获取某条记录的详细信息（含风险扫描结果）"""
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT results_json FROM history WHERE id = ?", (history_id,)).fetchone()
    conn.close()
    if row:
        data = json.loads(row[0])
        # 兼容旧数据（没有 hidden_risks 字段的记录）
        if isinstance(data, dict) and "all_results" in data:
            return data  # {"all_results": [...], "hidden_risks": [...]}
        else:
            return {"all_results": data, "hidden_risks": []}
    return None


def delete_history(history_id: int):
    """删除某条记录"""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM history WHERE id = ?", (history_id,))
    conn.commit()
    conn.close()

def update_latest_risks(risks: list):
    """更新最近一条记录的风险扫描结果"""
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT id, results_json FROM history ORDER BY id DESC LIMIT 1").fetchone()
    if row:
        rec_id, old_json = row
        data = json.loads(old_json)
        if isinstance(data, dict):
            data["hidden_risks"] = risks
        else:
            data = {"all_results": data, "hidden_risks": risks}
        conn.execute("UPDATE history SET results_json = ? WHERE id = ?", 
                     (json.dumps(data, ensure_ascii=False), rec_id))
        conn.commit()
    conn.close()    