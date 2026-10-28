"""SQLite 로컬 캐시. 데이터가 매일 누적되도록 설계."""
import os, sqlite3, json, time
import pandas as pd

DB_PATH = os.environ.get("SHORTDASH_DB", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "shortdash.sqlite"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS prices(ticker TEXT, date TEXT, open REAL, high REAL, low REAL, close REAL, volume REAL, PRIMARY KEY(ticker,date));
CREATE TABLE IF NOT EXISTS short_vol(ticker TEXT, date TEXT, short_vol REAL, short_exempt REAL, total_vol REAL, PRIMARY KEY(ticker,date));
CREATE TABLE IF NOT EXISTS finra_days(date TEXT PRIMARY KEY, status TEXT, fetched REAL);
CREATE TABLE IF NOT EXISTS short_interest(ticker TEXT, settle_date TEXT, si REAL, avg_vol REAL, dtc REAL, PRIMARY KEY(ticker,settle_date));
CREATE TABLE IF NOT EXISTS borrow(ticker TEXT, ts TEXT, available REAL, fee REAL, source TEXT, PRIMARY KEY(ticker,ts,source));
CREATE TABLE IF NOT EXISTS ftd(ticker TEXT, date TEXT, qty REAL, price REAL, PRIMARY KEY(ticker,date));
CREATE TABLE IF NOT EXISTS ftd_files(name TEXT PRIMARY KEY, fetched REAL);
CREATE TABLE IF NOT EXISTS threshold(ticker TEXT, date TEXT, PRIMARY KEY(ticker,date));
CREATE TABLE IF NOT EXISTS threshold_days(date TEXT PRIMARY KEY, status TEXT);
CREATE TABLE IF NOT EXISTS universe(ticker TEXT PRIMARY KEY, name TEXT, mcap REAL, price REAL, pct REAL, updated TEXT);
CREATE TABLE IF NOT EXISTS filings(ticker TEXT, form TEXT, filed TEXT, accession TEXT, items TEXT, PRIMARY KEY(ticker,accession));
CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT, ts REAL);
CREATE TABLE IF NOT EXISTS bt_runs(id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, label TEXT, params TEXT, metrics TEXT);
CREATE TABLE IF NOT EXISTS bt_samples(run_id INTEGER, ticker TEXT, asof TEXT, split TEXT, score REAL, level INTEGER, confluence INTEGER, flagged INTEGER, feats TEXT, hit INTEGER, max_ret REAL, end_ret REAL, min_ret REAL);
CREATE TABLE IF NOT EXISTS calibration(run_id INTEGER, bin INTEGER, lo REAL, hi REAL, n INTEGER, hits INTEGER);
CREATE TABLE IF NOT EXISTS scans(ts TEXT, kind TEXT, ticker TEXT, data TEXT);
CREATE TABLE IF NOT EXISTS journal(id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT, ticker TEXT, side TEXT, entry REAL, exit REAL, shares REAL, stop REAL, reason TEXT, notes TEXT);
CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS source_status(name TEXT PRIMARY KEY, ok INTEGER, msg TEXT, ts TEXT);
"""

def conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    c = sqlite3.connect(DB_PATH, timeout=60)
    c.execute("PRAGMA journal_mode=WAL")
    return c

def init():
    c = conn(); c.executescript(SCHEMA); c.commit(); c.close()

def q(sql, params=()):
    c = conn()
    try:
        return pd.read_sql_query(sql, c, params=params)
    finally:
        c.close()

def exec_(sql, params=()):
    c = conn()
    try:
        cur = c.execute(sql, params); c.commit(); return cur.lastrowid
    finally:
        c.close()

def upsert_rows(table, cols, rows):
    if not rows: return 0
    ph = ",".join("?" * len(cols))
    c = conn()
    try:
        c.executemany(f"INSERT OR REPLACE INTO {table}({','.join(cols)}) VALUES({ph})", rows); c.commit()
    finally:
        c.close()
    return len(rows)

def upsert_df(table, df, cols):
    if df is None or len(df) == 0: return 0
    rows = []
    for r in df[cols].itertuples(index=False):
        rows.append(tuple(None if (isinstance(v, float) and v != v) else (v.item() if hasattr(v, "item") else v) for v in r))
    return upsert_rows(table, cols, rows)

def kv_get(k, ttl=None):
    c = conn()
    try:
        r = c.execute("SELECT v, ts FROM kv WHERE k=?", (k,)).fetchone()
    finally:
        c.close()
    if not r: return None
    if ttl is not None and time.time() - r[1] > ttl: return None
    return json.loads(r[0])

def kv_set(k, v):
    exec_("INSERT OR REPLACE INTO kv(k,v,ts) VALUES(?,?,?)", (k, json.dumps(v, default=str), time.time()))

def get_setting(k, default=None):
    c = conn()
    try:
        r = c.execute("SELECT v FROM settings WHERE k=?", (k,)).fetchone()
    finally:
        c.close()
    return json.loads(r[0]) if r else default

def set_setting(k, v):
    exec_("INSERT OR REPLACE INTO settings(k,v) VALUES(?,?)", (k, json.dumps(v)))

def set_status(name, ok, msg=""):
    exec_("INSERT OR REPLACE INTO source_status(name,ok,msg,ts) VALUES(?,?,?,?)", (name, int(bool(ok)), str(msg)[:300], now_kst()))

init()

def now_kst():
    import datetime as _dt
    return (_dt.datetime.utcnow() + _dt.timedelta(hours=9)).strftime("%Y-%m-%d %H:%M KST")
