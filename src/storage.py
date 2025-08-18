"""Lightweight persistence for recent scores and CSV export. 
Stores only aggregates/metrics—never full message content."""

import os, sqlite3, json, time
from typing import Dict

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
os.makedirs(DB_PATH, exist_ok=True)
DB_FILE = os.path.join(DB_PATH, "toxicity.db")

def _conn():
    con = sqlite3.connect(DB_FILE)
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA foreign_keys=ON;")
    return con

def _init():
    con=_conn(); cur=con.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS messages(
        id TEXT PRIMARY KEY,
        user_id TEXT, channel_id TEXT, guild_id TEXT,
        created_at INTEGER, scores_json TEXT, triggered INTEGER
    );
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS policies(
        guild_id TEXT, channel_id TEXT, label TEXT, threshold REAL,
        PRIMARY KEY (guild_id, channel_id, label)
    );
    """)
    con.commit(); con.close()
_init()

def record_message(mid, uid, cid, gid, scores: Dict[str,float], triggered:int):
    con=_conn()
    con.execute("INSERT OR REPLACE INTO messages VALUES(?,?,?,?,?,?,?)",
                (mid, uid, cid, gid, int(time.time()), json.dumps(scores), int(triggered)))
    con.commit(); con.close()

def fetch_recent_user_scores(uid: str, gid: str, days: int = 7):
    cutoff = int(time.time()) - days*86400
    con=_conn(); cur=con.cursor()
    cur.execute("SELECT created_at, scores_json FROM messages WHERE user_id=? AND guild_id=? AND created_at>=? ORDER BY created_at ASC",
                (uid, gid, cutoff))
    rows = [(int(ts), json.loads(js)) for (ts, js) in cur.fetchall()]
    con.close(); return rows

def purge_older_than(days:int=30):
    cutoff = int(time.time()) - days*86400
    con=_conn(); con.execute("DELETE FROM messages WHERE created_at < ?", (cutoff,))
    con.commit(); con.close()

def upsert_policy(gid:str, cid:str, label:str, thr:float):
    con=_conn()
    con.execute("INSERT INTO policies VALUES(?,?,?,?) ON CONFLICT(guild_id,channel_id,label) DO UPDATE SET threshold=excluded.threshold",
                (gid,cid,label,thr))
    con.commit(); con.close()

def get_threshold(gid:str, cid:str, label:str):
    con=_conn(); cur=con.cursor()
    cur.execute("SELECT threshold FROM policies WHERE guild_id=? AND channel_id=? AND label=?",
                (gid,cid,label))
    row=cur.fetchone(); con.close()
    return float(row[0]) if row else None
