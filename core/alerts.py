"""급등 신호 폰 알림 (ntfy 기본 · 텔레그램 선택) + 중복 방지 + 알림 기록 + 사후 자동 채점.

상태 저장 위치 (PC·클라우드 공통):
  data/alerts/alerts_log.json   보낸/억제된 알림 기록 (최근 2000건) — 대시보드와 채점이 읽음
  data/alerts/alert_state.json  중복 방지용 마지막 전송 시각
  + SQLite alerts 테이블(같은 내용 사본)
GitHub Actions 에선 이 폴더를 alert-data 브랜치에 커밋해 다음 실행으로 넘깁니다."""
import os, json, time, secrets, datetime as dt
from zoneinfo import ZoneInfo
import requests
import pandas as pd
from . import db, toss

KST, ET = ZoneInfo("Asia/Seoul"), ZoneInfo("America/New_York")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ALERT_DIR = os.environ.get("SHORTDASH_ALERT_DIR", os.path.join(ROOT, "data", "alerts"))
LOG_PATH = os.path.join(ALERT_DIR, "alerts_log.json")
STATE_PATH = os.path.join(ALERT_DIR, "alert_state.json")
CFG_PATH = os.path.join(ALERT_DIR, "alert_cfg.json")   # 주제 이름(비밀)은 넣지 않음
COST = 0.006          # 왕복 비용 (검증과 동일)
H = 10                # 채점 기간 (거래일)

TYPE_KO = {"prob": "상위 확률 신호", "cover": "커버 압력", "reignite": "재점화 돌파", "rvol": "거래량 급증", "pregap": "프리마켓 갭", "test": "테스트"}

DEFAULTS = {
    "enabled": True,
    "channel": "ntfy",            # ntfy | telegram | both
    "ntfy_server": "https://ntfy.sh",
    "ntfy_topic": "",             # 비어 있으면 처음 불러올 때 무작위 생성
    "types": ["prob", "cover", "reignite", "rvol", "pregap"],
    "prob_min": 0.0,              # 0 = 검증 모델의 상위 5% 기준(flag) 사용, >0 이면 보정확률 % 기준
    "cp_min": 70.0,               # 커버 압력 지수 기준 (0~100)
    "rvol_on": True,              # 라이브 5분 거래량 급증 트리거 사용
    "gap_min": 20.0,              # 프리마켓 갭 기준 %
    "min_level": 3,               # 최소 레벨 (1~5)
    "cooldown_min": 120,          # 같은 종목·같은 신호 재알림 간격 (분)
    "quiet_on": False, "quiet_start": "01:00", "quiet_end": "07:00", "quiet_mode": "silent",   # silent=무음 전송, skip=보내지 않음(기록만)
    "penalty_mode": "mark",       # mark=⚠ 표시 후 전송, suppress=보내지 않음(기록만)
    "toss_mode": "onelink",
    "max_tickers": 25,
}

# ---------------------------------------------------------------- 설정
def _secret(name):
    v = os.environ.get(name)
    if v: return v
    try:
        import streamlit as st
        return st.secrets.get(name) if hasattr(st, "secrets") else None
    except Exception:
        return None

def new_topic():
    return "shortradar-" + secrets.token_hex(8)

def cfg():
    c = dict(DEFAULTS); c.update(db.get_setting("alert_cfg", {}) or {})
    # 클라우드: 대시보드에서 저장한 설정 파일(alert-data 브랜치의 data/alerts/alert_cfg.json)이 우선
    fc = None
    try: fc = json.load(open(CFG_PATH, encoding="utf-8")) if os.path.exists(CFG_PATH) else None
    except Exception: fc = None
    if fc is None and _secret("GH_REPO") and _secret("GH_TOKEN") and not os.environ.get("GITHUB_ACTIONS"):
        fc = remote_get("data/alerts/alert_cfg.json")
    if isinstance(fc, dict): c.update({k: v for k, v in fc.items() if k in DEFAULTS and k != "ntfy_topic"})
    if not c.get("ntfy_topic"):
        c["ntfy_topic"] = new_topic(); save_cfg(c)
    for k, env in (("ntfy_topic", "NTFY_TOPIC"), ("ntfy_server", "NTFY_SERVER")):
        v = _secret(env)
        if v: c[k] = v; c[f"{k}_from_secret"] = True
    c["tg_token"], c["tg_chat"] = _secret("TELEGRAM_BOT_TOKEN"), _secret("TELEGRAM_CHAT_ID")
    c["dash_url"] = _secret("DASH_URL") or db.get_setting("dash_url", "")
    return c

def save_cfg(c):
    """로컬 DB 에 저장. 클라우드(GH_REPO+GH_TOKEN 설정)면 alert-data 브랜치에도 올려 GitHub Actions 스캐너가 같은 설정을 쓰게 함.
    반환: 원격 저장 결과 (None=로컬만, True/False)."""
    keep = {k: c[k] for k in DEFAULTS if k in c}
    db.set_setting("alert_cfg", keep)
    if _secret("GH_REPO") and _secret("GH_TOKEN"):
        pub = {k: v for k, v in keep.items() if k != "ntfy_topic"}       # 주제 이름은 Secrets 로만
        ok = remote_put("data/alerts/alert_cfg.json", pub, "대시보드에서 알림 설정 변경")
        db.exec_("DELETE FROM kv WHERE k=?", ("remote:data/alerts/alert_cfg.json",))
        return ok
    return None

def _gh():
    repo, tok = _secret("GH_REPO"), _secret("GH_TOKEN")
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if tok: h["Authorization"] = f"Bearer {tok}"
    return repo, _secret("GH_ALERT_BRANCH") or "alert-data", h

def remote_get(path, ttl=120):
    """alert-data 브랜치의 JSON 파일 읽기 (kv 캐시 ttl 초)."""
    repo, br, h = _gh()
    if not repo: return None
    k = f"remote:{path}"
    v = db.kv_get(k, ttl)
    if v is not None: return v.get("v")
    try:
        r = requests.get(f"https://api.github.com/repos/{repo}/contents/{path}?ref={br}", headers=dict(h, Accept="application/vnd.github.raw+json"), timeout=15)
        out = r.json() if r.status_code == 200 else None
        if r.status_code in (200, 404): db.kv_set(k, {"v": out})
        return out
    except Exception:
        return None

def remote_put(path, obj, msg):
    import base64
    repo, br, h = _gh()
    try:
        r = requests.get(f"https://api.github.com/repos/{repo}/contents/{path}?ref={br}", headers=h, timeout=15)
        sha = r.json().get("sha") if r.status_code == 200 else None
        body = {"message": msg, "branch": br, "content": base64.b64encode(json.dumps(obj, ensure_ascii=False, indent=1).encode()).decode()}
        if sha: body["sha"] = sha
        r = requests.put(f"https://api.github.com/repos/{repo}/contents/{path}", headers=h, json=body, timeout=20)
        return r.status_code in (200, 201)
    except Exception:
        return False

# ---------------------------------------------------------------- 전송
def send_ntfy(c, title, body, click=None, priority=4, tags=None, actions=None):
    payload = {"topic": c["ntfy_topic"], "title": title, "message": body, "priority": int(priority), "tags": tags or []}
    if click: payload["click"] = click
    if actions: payload["actions"] = actions
    try:
        r = requests.post(c["ntfy_server"].rstrip("/"), json=payload, timeout=15)
        return r.status_code
    except Exception as e:
        return f"ERR {type(e).__name__}"

def send_telegram(c, title, body, click=None):
    if not c.get("tg_token") or not c.get("tg_chat"): return "no-config"
    txt = f"{title}\n{body}" + (f"\n토스: {click}" if click else "")
    try:
        r = requests.post(f"https://api.telegram.org/bot{c['tg_token']}/sendMessage", data={"chat_id": c["tg_chat"], "text": txt[:4000], "disable_web_page_preview": True}, timeout=15)
        return r.status_code
    except Exception as e:
        return f"ERR {type(e).__name__}"

def deliver(c, title, body, click=None, priority=4, tags=None, actions=None):
    res = {}
    if c["channel"] in ("ntfy", "both"): res["ntfy"] = send_ntfy(c, title, body, click, priority, tags, actions)
    if c["channel"] in ("telegram", "both"): res["telegram"] = send_telegram(c, title, body, click)
    return res

def ok(res):
    return any(v == 200 for v in res.values())

def test(c=None):
    c = c or cfg()
    url = toss.url("SOUN", c.get("toss_mode"))
    return deliver(c, "숏 레이더 테스트 알림", "이 알림이 보이면 연결 성공입니다. 누르면 토스증권 SOUN 화면으로 이동합니다.", click=url, priority=3, tags=["white_check_mark"])

# ---------------------------------------------------------------- 저장
def _load(path, default):
    try:
        with open(path, encoding="utf-8") as fh: return json.load(fh)
    except Exception:
        return default

def _save(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh: json.dump(obj, fh, ensure_ascii=False, indent=1, default=str)
    os.replace(tmp, path)

def load_log():
    return _load(LOG_PATH, [])

def save_log(log):
    _save(LOG_PATH, log[-2000:])

def _ensure_table():
    db.exec_("CREATE TABLE IF NOT EXISTS alerts(id TEXT PRIMARY KEY, ts TEXT, ticker TEXT, types TEXT, sent INTEGER, data TEXT)")

def _db_put(rec):
    try:
        _ensure_table()
        db.exec_("INSERT OR REPLACE INTO alerts(id,ts,ticker,types,sent,data) VALUES(?,?,?,?,?,?)",
                 (rec["id"], rec["ts_kst"], rec["ticker"], ",".join(rec["types"]), int(bool(rec.get("sent"))), json.dumps(rec, ensure_ascii=False, default=str)))
    except Exception:
        pass

# ---------------------------------------------------------------- 판정
def _in_quiet(c, now=None):
    if not c.get("quiet_on"): return False
    now = (now or dt.datetime.now(KST)).astimezone(KST)
    m = now.hour * 60 + now.minute
    s = int(c["quiet_start"][:2]) * 60 + int(c["quiet_start"][3:5]); e = int(c["quiet_end"][:2]) * 60 + int(c["quiet_end"][3:5])
    return (s <= m < e) if s <= e else (m >= s or m < e)

def penalties(x):
    """증자·역분할 등 감점 요인 (알림에 ⚠ 표시 또는 억제)."""
    out = []
    b = x.get("b")
    try:
        fil = b.fil
        if len(fil):
            asof = pd.Timestamp(dt.date.today())
            r = fil[(fil["filed"] >= asof - pd.Timedelta(days=30)) & fil["form"].str.match(r"^424B")]
            if len(r): out.append(f"424B 증자 설명서 {len(r)}건 (30일 내, 최근 {r['filed'].max():%m/%d})")
            rs = fil[(fil["filed"] >= asof - pd.Timedelta(days=90)) & (fil["form"] == "8-K") & fil["items"].str.contains("3.03|5.03", na=False)]
            if len(rs): out.append("역분할 관련 8-K (90일 내)")
    except Exception:
        pass
    sp = [s for s in ((x.get("info") or {}).get("splits") or []) if s[1] < 1]
    if sp:
        try:
            last = pd.Timestamp(sp[-1][0])
            if last >= pd.Timestamp(dt.date.today()) - pd.Timedelta(days=90): out.append(f"역분할 {last:%Y-%m-%d}")
        except Exception:
            pass
    d = x.get("dil") or {}
    if d.get("score", 0) >= 60: out.append(f"희석 위험 {d['score']:.0f}/100")
    return out

def evaluate(x, c, session):
    """snapshot 결과 → 발생한 신호 목록 [(type, 설명)]."""
    s, f, eh = x["s"], x["f"], x.get("eh") or {}
    sig = []
    lvl = int(s.get("level", 0))
    pr = s.get("rprob")
    if lvl < int(c["min_level"]): return sig, lvl
    T = set(c["types"])
    if "prob" in T:
        hit = (pr is not None and pr >= float(c["prob_min"])) if float(c["prob_min"]) > 0 else bool(s.get("flagged"))
        if hit: sig.append(("prob", f"검증 모델 상위 신호 (보정확률 {pr:.0f}%)" if pr is not None else "검증 모델 상위 신호"))
    if "cover" in T and float(f.get("cover_pressure") or 0) >= float(c["cp_min"]):
        sig.append(("cover", f"커버 압력 {f['cover_pressure']:.0f}/100"))
    trig = dict(x.get("triggers") or [])
    if "reignite" in T and "reignite" in trig: sig.append(("reignite", trig["reignite"]))
    if "rvol" in T and c.get("rvol_on", True) and "volume" in trig: sig.append(("rvol", trig["volume"]))
    if "pregap" in T and session == "pre" and (eh.get("pre_gap") or 0) >= float(c["gap_min"]):
        sig.append(("pregap", f"프리마켓 갭 {eh['pre_gap']:+.1f}%"))
    return sig, lvl

def grade_levels(price, rl, stop, ph):
    """사후 채점 기준: 목표 = 재점화 레벨(이미 넘었으면 다음 저항 ph), 손절 = 매수구간 손절."""
    if not price or not stop or stop >= price * 0.995: return None, None
    tgt = rl if rl and rl > price * 1.005 else (ph if ph and ph > price * 1.005 else None)
    return tgt, stop

def compose(t, x, sig, pens, c, session):
    f, s, eh, bz, meta = x["f"], x["s"], x.get("eh") or {}, x.get("bz") or {}, x.get("meta") or {}
    price = eh.get("last") or f.get("live_price") or f["price"]
    chg = (price / eh["prev_close"] - 1) * 100 if eh.get("prev_close") else None
    from . import live
    title = f"🚀 {t} {' · '.join(TYPE_KO[k] for k, _ in sig)}"
    lines = [f"${price:.3f}" + (f" ({chg:+.1f}%)" if chg is not None else "") + f" · {live.SESSION_KO.get(session, session)} · 레벨 {s['level']} · 점수 {s['score']:.0f}"]
    summ = (x.get("summary") or "").strip().split("\n")[0]
    if summ: lines.append(summ[:120])
    lines += [f"• {m}" for _, m in sig]
    pr = s.get("rprob")
    lines.append(f"10일 내 셋업 성공 확률(보정): {pr:.0f}%" if pr is not None else "확률: 데이터 부족")
    bp = x.get("bp") or {}
    if bp.get("price"):
        why = f"기준가 ${bp['refp']:.3f}의 −5%" if bp.get("kind") == "pct5" else f"{bp['name']}, 기준가 대비 {bp['pct']:+.1f}%"
        lines.append(f"추천 매수가 ${bp['price']:.3f} 지정가({why}) · 체결 가능성 약 {bp['fill'] * 100:.0f}% · 손익분기 ${bp['break_even']:.3f}")
    elif bp.get("reason") == "stop":
        lines.append("추천 매수가 없음: −5% 가격이 손절선과 너무 가까움")
    if bz:
        lines.append(f"숏 지지구간 ${bz['zone'][0]:.3f}–${bz['zone'][1]:.3f} · 손절 ${bz['stop']:.3f} · 1차목표 ${bz['tp1']:.3f}")
    for p_ in pens: lines.append(f"⚠ {p_}")
    lines.append("추정치·투자권유 아님 · 누르면 토스증권")
    return title, "\n".join(lines), price

def run(snapshots, session, now=None, dry=False, c=None):
    """snapshots: [(ticker, snapshot dict)] → 알림 판정·전송·기록. 반환: 이번에 만든 기록 목록."""
    c = c or cfg()
    now = now or time.time()
    state = _load(STATE_PATH, {})
    log = load_log(); new = []
    quiet = _in_quiet(c)
    for t, x in snapshots:
        if not x: continue
        sig, lvl = evaluate(x, c, session)
        fresh = [(k, m) for k, m in sig if now - float(state.get(f"{t}:{k}", 0)) >= float(c["cooldown_min"]) * 60]
        if not fresh: continue
        pens = penalties(x)
        title, body, price = compose(t, x, fresh, pens, c, session)
        url = toss.url(t, c.get("toss_mode"))
        bz, meta = x.get("bz") or {}, x.get("meta") or {}
        rl = float(meta.get("reignite") or 0) or None
        ph = float(meta.get("hi21") or 0) or None
        tgt, stp = grade_levels(price, rl, bz.get("stop"), max(ph or 0, bz.get("tp2") or 0) or None)
        why_not = None
        if pens and c["penalty_mode"] == "suppress": why_not = "감점 요인으로 억제"
        elif quiet and c["quiet_mode"] == "skip": why_not = "방해 금지 시간"
        elif not c.get("enabled", True): why_not = "알림 꺼짐"
        res = {}
        if not why_not and not dry:
            acts = [{"action": "view", "label": "토스에서 열기", "url": url, "clear": True}]
            if c.get("dash_url"): acts.append({"action": "view", "label": "대시보드", "url": f"{c['dash_url'].rstrip('/')}/?p=stock&t={t}"})
            res = deliver(c, title, body, click=url, priority=2 if quiet else (5 if any(k in ("reignite", "pregap") for k, _ in fresh) else 4),
                          tags=["rocket"] + (["warning"] if pens else []), actions=acts)
        sent = ok(res)
        for k, _ in fresh:
            if sent or why_not or dry: state[f"{t}:{k}"] = now      # 억제된 것도 쿨다운 적용 (도배 방지)
        nk = dt.datetime.fromtimestamp(now, KST)
        rec = {"id": f"{t}-{int(now)}", "ts_kst": nk.strftime("%Y-%m-%d %H:%M"), "ts_utc": dt.datetime.fromtimestamp(now, dt.timezone.utc).isoformat(timespec="seconds"),
               "date_et": dt.datetime.fromtimestamp(now, ET).strftime("%Y-%m-%d"), "session": session,
               "ticker": t, "types": [k for k, _ in fresh], "msgs": [m for _, m in fresh], "title": title, "body": body,
               "price": round(float(price), 4), "level": lvl, "score": x["s"]["score"], "prob": x["s"].get("rprob"),
               "cp": x["f"].get("cover_pressure"), "rl": rl, "stop": bz.get("stop"), "zone": list(bz["zone"]) if bz else None, "bp": round(float((x.get("bp") or {}).get("price") or 0), 4) or None,
               "tgt": tgt, "stp": stp, "penalties": pens, "sent": sent, "result": res, "suppressed": why_not, "dry": dry,
               "toss_url": url, "grade": "open" if tgt else "n/a"}
        log.append(rec); new.append(rec); _db_put(rec)
    _save(STATE_PATH, {k: v for k, v in state.items() if now - float(v) < 7 * 86400})
    save_log(log)
    return new

# ---------------------------------------------------------------- 사후 자동 채점 (셋업 정의)
def _score(fut, price, tgt, stop):
    """보수적: 같은 날 손절·목표 동시 터치 → 손절 우선. 50% 목표 익절 후 본전 스탑, 나머지 10일 종가."""
    pos, real, st_, tp_done = 1.0, 0.0, stop, False
    for i, r in enumerate(fut.itertuples(index=False), 1):
        o, h, l = float(r.open), float(r.high), float(r.low)
        if l <= st_:
            real += pos * (min(o, st_) / price - 1)
            return ("miss" if not tp_done else "hit"), i, real - COST
        if not tp_done and h >= tgt:
            real += 0.5 * (max(o, tgt) / price - 1); pos, st_, tp_done = 0.5, price, True
            hit_day = i
    if len(fut) >= H:
        real += pos * (float(fut["close"].iloc[-1]) / price - 1)
        return ("hit" if tp_done else "miss"), (hit_day if tp_done else len(fut)), real - COST
    return ("open_hit" if tp_done else "open"), None, None

def daily_bars(t, start):
    px = db.q("SELECT date, open, high, low, close FROM prices WHERE ticker=? AND date>? ORDER BY date", (t, start))
    if len(px) >= H: return px.head(H)
    try:
        import yfinance as yf
        h = yf.Ticker(t).history(start=start, auto_adjust=False)
        if len(h):
            h = h.reset_index(); h["date"] = h["Date"].dt.strftime("%Y-%m-%d")
            h = h.rename(columns={"Open": "open", "High": "high", "Low": "low", "Close": "close"})
            return h[h["date"] > start][["date", "open", "high", "low", "close"]].head(H)
    except Exception:
        pass
    return px

def grade_all(log=None, save=True):
    """'open' 알림을 알림 다음 거래일부터 10거래일 일봉으로 채점: 목표(재점화 레벨) 먼저 = hit, 손절 먼저/기간 내 미도달 = miss."""
    log = log if log is not None else load_log()
    changed = 0
    for r in log:
        if r.get("grade") not in ("open", "open_hit") or r.get("dry") or not r.get("tgt"): continue
        fut = daily_bars(r["ticker"], r["date_et"])
        if len(fut) == 0: continue
        g, day, ret = _score(fut, r["price"], r["tgt"], r["stp"])
        if g != r.get("grade") or ret is not None:
            r.update({"grade": g, "grade_day": day, "grade_ret": ret, "graded_bars": len(fut)}); changed += 1
    if save and changed: save_log(log)
    return log

def forward_stats(log=None, only_sent=False):
    """채점 완료된 알림의 적중률 (Wilson 95% CI) 과 평균 수익(비용 0.6% 차감)."""
    log = log if log is not None else load_log()
    rows = [r for r in log if not r.get("dry") and r.get("grade") in ("hit", "miss") and (r.get("sent") or not only_sent)]
    n = len(rows); k = sum(r["grade"] == "hit" for r in rows)
    out = {"n": n, "hits": k, "open": sum(r.get("grade") in ("open", "open_hit") for r in log if not r.get("dry")),
           "total": sum(not r.get("dry") for r in log)}
    if n:
        import math
        p = k / n; z = 1.96; d = 1 + z * z / n
        c = (p + z * z / (2 * n)) / d; w = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
        rets = [r["grade_ret"] for r in rows if r.get("grade_ret") is not None]
        out.update({"rate": p * 100, "ci": ((c - w) * 100, (c + w) * 100), "avg_ret": (sum(rets) / len(rets) * 100) if rets else None})
    return out

# ---------------------------------------------------------------- 대시보드용: 로그 읽기 (클라우드면 GitHub alert-data 브랜치)
def fetch_remote_log(ttl=120):
    return remote_get("data/alerts/alerts_log.json", ttl)

def dashboard_log():
    """원격(GitHub) 로그가 설정돼 있으면 그것, 아니면 로컬 파일."""
    r = fetch_remote_log()
    return (r, "GitHub alert-data 브랜치") if r is not None else (load_log(), "이 컴퓨터")
