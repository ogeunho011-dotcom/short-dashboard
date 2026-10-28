"""클라우드 모드: GitHub Actions 가 매일 만든 DB 스냅샷(릴리스 'db-latest' 의 shortdash.sqlite.gz)을 받아 쓰기.

- Streamlit Community Cloud 는 컴퓨터가 잠들면 파일이 지워지므로, 매번 처음부터 데이터를 모으는 대신
  GitHub 에 올려 둔 최신 DB 를 내려받습니다 (약 50MB, 보통 10~30초).
- 이 화면에서 바꾼 설정(settings)·매매일지(journal)는 DB 를 교체할 때 그대로 옮겨 둡니다.
- Secrets 에 GH_REPO + GH_TOKEN 이 없으면 아무것도 하지 않습니다 (PC 로컬 모드).
"""
import os, gzip, shutil, sqlite3, time, json
import requests
from . import db

TAG = "db-latest"
ASSET = "shortdash.sqlite.gz"
KEEP_TABLES = ("settings", "journal")

def _secret(name):
    from .alerts import _secret as s
    return s(name)

def enabled():
    return bool(_secret("GH_REPO") and _secret("GH_TOKEN"))

def _h(raw=False):
    return {"Authorization": f"Bearer {_secret('GH_TOKEN')}", "X-GitHub-Api-Version": "2022-11-28",
            "Accept": "application/octet-stream" if raw else "application/vnd.github+json"}

def _marker():
    return db.DB_PATH + ".asset.json"

def remote_asset():
    """릴리스 자산 정보 (id, updated_at, size) 또는 None."""
    r = requests.get(f"https://api.github.com/repos/{_secret('GH_REPO')}/releases/tags/{_secret('DB_RELEASE_TAG') or TAG}", headers=_h(), timeout=20)
    if r.status_code != 200: return None
    for a in r.json().get("assets", []):
        if a["name"] == ASSET: return {"id": a["id"], "updated_at": a["updated_at"], "size": a["size"], "url": a["url"]}
    return None

def local_asset():
    try: return json.load(open(_marker()))
    except Exception: return None

def sync_db(min_interval=900, progress=None):
    """원격 스냅샷이 로컬보다 새로우면 내려받아 교체. 반환: 'updated' / 'same' / 'none' / 'off' / 'error:...'."""
    if not enabled(): return "off"
    la = local_asset() or {}
    if la.get("checked") and time.time() - la["checked"] < min_interval and os.path.exists(db.DB_PATH): return "same"
    try:
        ra = remote_asset()
        if not ra: return "none"
        if la.get("updated_at") == ra["updated_at"] and os.path.exists(db.DB_PATH):
            json.dump(dict(la, checked=time.time()), open(_marker(), "w")); return "same"
        if progress: progress(f"최신 데이터 받는 중 ({ra['size'] / 1e6:.0f}MB)…")
        tmp_gz, tmp = db.DB_PATH + ".dl.gz", db.DB_PATH + ".dl"
        os.makedirs(os.path.dirname(db.DB_PATH), exist_ok=True)
        with requests.get(ra["url"], headers=_h(raw=True), stream=True, timeout=120) as r:
            r.raise_for_status()
            with open(tmp_gz, "wb") as f:
                for ch in r.iter_content(1 << 20): f.write(ch)
        with gzip.open(tmp_gz, "rb") as g, open(tmp, "wb") as f: shutil.copyfileobj(g, f)
        os.remove(tmp_gz)
        if os.path.exists(db.DB_PATH):                       # 내 설정 · 매매일지 옮기기
            c = sqlite3.connect(tmp)
            try:
                c.execute("ATTACH DATABASE ? AS old", (db.DB_PATH,))
                for t in KEEP_TABLES:
                    try:
                        c.execute(f"DELETE FROM main.{t}"); c.execute(f"INSERT INTO main.{t} SELECT * FROM old.{t}")
                    except sqlite3.Error: pass
                c.commit(); c.execute("DETACH DATABASE old")
            finally: c.close()
        for ext in ("-wal", "-shm"):
            try: os.remove(db.DB_PATH + ext)
            except FileNotFoundError: pass
        os.replace(tmp, db.DB_PATH)
        json.dump(dict(ra, checked=time.time()), open(_marker(), "w"))
        db.init()
        return "updated"
    except Exception as e:
        return f"error:{type(e).__name__}: {str(e)[:120]}"

def snapshot(out_gz, drop_personal=True):
    """(GitHub Actions 에서) 현재 DB 를 압축 스냅샷으로. 개인 데이터(매매일지)는 비움."""
    tmp = out_gz + ".tmp.sqlite"
    if os.path.exists(tmp): os.remove(tmp)
    c = sqlite3.connect(db.DB_PATH); c.execute("VACUUM INTO ?", (tmp,)); c.close()
    if drop_personal:
        c = sqlite3.connect(tmp); c.execute("DELETE FROM journal")
        c.execute("DELETE FROM settings WHERE k IN ('alert_cfg','telegram','tg_token','tg_chat')")   # 알림 주제·토큰은 스냅샷에 넣지 않음
        c.commit(); c.execute("VACUUM"); c.close()
    with open(tmp, "rb") as f, gzip.open(out_gz, "wb", 6) as g: shutil.copyfileobj(f, g)
    os.remove(tmp)
    return os.path.getsize(out_gz)

if __name__ == "__main__":
    import sys
    if sys.argv[1:2] == ["snapshot"]:
        print("snapshot bytes:", snapshot(sys.argv[2]))
