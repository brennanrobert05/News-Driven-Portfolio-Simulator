# db.py
# SQLite database for transparency/auditability:
# - stores news headlines
# - stores sentiment results
# - stores portfolio snapshots
# - stores decision logs

import json
import sqlite3
from typing import Any, Dict, List

DB_PATH = "portfolio.db"

def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con

def init_db() -> None:
    con = _conn()
    cur = con.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS news (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fetched_at TEXT NOT NULL,
        title TEXT NOT NULL,
        source TEXT,
        published TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS sentiment (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        news_id INTEGER NOT NULL,
        analyzed_at TEXT NOT NULL,
        label TEXT NOT NULL,
        compound REAL NOT NULL,
        impact_label TEXT NOT NULL,
        impact_score REAL NOT NULL,
        category TEXT NOT NULL,
        FOREIGN KEY(news_id) REFERENCES news(id)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS portfolio_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL,
        regime TEXT NOT NULL,
        portfolio_name TEXT NOT NULL,
        weights_json TEXT NOT NULL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS decision_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL,
        regime TEXT NOT NULL,
        message TEXT NOT NULL
    )
    """)

    con.commit()
    con.close()

def insert_news(fetched_at: str, title: str, source: str, published: str) -> int:
    con = _conn()
    cur = con.cursor()
    cur.execute(
        "INSERT INTO news (fetched_at, title, source, published) VALUES (?, ?, ?, ?)",
        (fetched_at, title, source, published),
    )
    con.commit()
    news_id = int(cur.lastrowid)
    con.close()
    return news_id

def insert_sentiment(
    news_id: int,
    analyzed_at: str,
    label: str,
    compound: float,
    impact_label: str,
    impact_score: float,
    category: str,
) -> None:
    con = _conn()
    cur = con.cursor()
    cur.execute(
        """INSERT INTO sentiment
           (news_id, analyzed_at, label, compound, impact_label, impact_score, category)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (news_id, analyzed_at, label, float(compound), impact_label, float(impact_score), category),
    )
    con.commit()
    con.close()

def log_decision(created_at: str, regime: str, message: str) -> None:
    con = _conn()
    cur = con.cursor()
    cur.execute(
        "INSERT INTO decision_log (created_at, regime, message) VALUES (?, ?, ?)",
        (created_at, regime, message),
    )
    con.commit()
    con.close()

def get_recent_decisions(limit: int = 10) -> List[Dict[str, Any]]:
    con = _conn()
    cur = con.cursor()
    cur.execute(
        "SELECT created_at, regime, message FROM decision_log ORDER BY id DESC LIMIT ?",
        (limit,),
    )
    rows = cur.fetchall()
    con.close()
    return [dict(r) for r in rows]

def save_portfolio_snapshot(created_at: str, regime: str, portfolio_name: str, weights: Dict[str, float]) -> None:
    con = _conn()
    cur = con.cursor()
    cur.execute(
        "INSERT INTO portfolio_snapshots (created_at, regime, portfolio_name, weights_json) VALUES (?, ?, ?, ?)",
        (created_at, regime, portfolio_name, json.dumps(weights, sort_keys=True)),
    )
    con.commit()
    con.close()