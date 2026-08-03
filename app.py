import sqlite3, os, requests
from datetime import datetime, timedelta
from pathlib import Path
from flask import Flask, request, jsonify
from functools import wraps

BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "records.db"
JST = timedelta(hours=8)
AUTH_TOKEN = os.environ.get("AUTH_TOKEN", "214016")
BARK_KEY = "cCjWQMTnoafzwUBChb38Bo"

LIMITS = {
    "抖音": 900,
    "哔哩哔哩": 1200,
    "淘宝": 900,
    "拼多多": 900,
    "微信": 1800,
    "小红书": 1200,
}

def init_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("""CREATE TABLE IF NOT EXISTS records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        app_name TEXT NOT NULL,
        event TEXT NOT NULL,
        timestamp TEXT NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS device (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        battery TEXT,
        location TEXT,
        volume TEXT,
        timestamp TEXT NOT NULL)""")
    conn.commit()
    conn.close()

init_db()

app = Flask(__name__)

def check_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.headers.get("Authorization", "")
        if auth != f"Bearer {AUTH_TOKEN}":
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated

def calc_sessions():
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()
    cur.execute("SELECT app_name, event, timestamp FROM records ORDER BY id ASC")
    rows = cur.fetchall()
    conn.close()
    sessions, opens = {}, {}
    for r in rows:
        app_name, ev, ts = r
        if ev == "open":
            opens[app_name] = datetime.fromisoformat(ts)
        elif ev == "close" and app_name in opens:
            gap = int((datetime.fromisoformat(ts) - opens[app_name]).total_seconds())
            sessions[app_name] = sessions.get(app_name, 0) + gap
            del opens[app_name]
    return sessions

def bark(title, content):
    try:
        url = f"https://api.day.app/{BARK_KEY}/{title}/{content}"
        requests.get(url, timeout=5)
    except:
        pass

def check_limits():
    sessions = calc_sessions()
    for app_name, secs in sessions.items():
        limit = LIMITS.get(app_name)
        if limit and secs >= limit:
            m = secs // 60
            bark("沈星回提醒", f"{app_name}用了{m}分钟了，休息一下")

def get_last_open():
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()
    cur.execute("SELECT app_name FROM records WHERE event='open' ORDER BY id DESC LIMIT 1")
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None

def get_device():
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()
    cur.execute("SELECT battery, location, volume, timestamp FROM device ORDER BY id DESC LIMIT 1")
    row = cur.fetchone()
    conn.close()
    if row:
        return {"battery": row[0], "location": row[1], "volume": row[2], "updated": row[3]}
    return {}

@app.route("/report", methods=["POST"])
@check_auth
def report():
    data = request.get_json()
    app_name = data.get("app_name")
    event = data.get("event")
    now = datetime.utcnow().isoformat()

    if event == "open":
        last = get_last_open()
        if last:
            conn = sqlite3.connect(str(DB_PATH))
            conn.execute("INSERT INTO records (app_name, event, timestamp) VALUES (?, ?, ?)",
                         (last, "close", now))
            conn.commit()
            conn.close()
            check_limits()

    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("INSERT INTO records (app_name, event, timestamp) VALUES (?, ?, ?)",
                 (app_name, event, now))
    conn.commit()
    conn.close()

    battery = data.get("battery")
    location = data.get("location")
    volume = data.get("volume")
    if battery or location or volume:
        conn = sqlite3.connect(str(DB_PATH))
        conn.execute("INSERT INTO device (battery, location, volume, timestamp) VALUES (?, ?, ?, ?)",
                     (battery, location, volume, now))
        conn.commit()
        conn.close()

    return jsonify({"status": "ok"})

@app.route("/ping")
def ping():
    return "pong"

@app.route("/activity/summary")
def summary():
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()
    cur.execute("SELECT app_name, event, timestamp FROM records ORDER BY id DESC LIMIT 5")
    recent = cur.fetchall()
    conn.close()
    sessions = calc_sessions()
    device = get_device()
    return jsonify({"recent_apps": [r[0] for r in recent], "sessions": sessions, "device": device})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
