"""급등 신호 알림 스캐너 (PC 반복 실행 · GitHub Actions 1회 실행 공용).

  python scripts/alerts_run.py              # 1회 (장 마감 시간이면 건너뜀)
  python scripts/alerts_run.py --loop 10    # 10분마다 반복 (프리·정규·애프터 시간에만)
  python scripts/alerts_run.py --session-loop   # GitHub Actions 장중 반복 (LOOP_INTERVAL_S 초 간격, LOOP_MAX_MIN 분 한도)
  python scripts/alerts_run.py --force      # 장 시간 무시하고 1회
  python scripts/alerts_run.py --test       # 테스트 알림만 전송
  python scripts/alerts_run.py --dry        # 판정만, 전송 안 함
  python scripts/alerts_run.py --grade      # 지난 알림 채점만
  python scripts/alerts_run.py --filings --dry   # 공시 판정만 (전송 안 함)
  (테스트용 다른 주제: 환경변수 NTFY_TOPIC 을 임시 주제로)

대상: (1) 핵심 = 관심종목 + '가능'·경보 전부 + '대기' 점수순 — 매번 전체 계산
      (2) 넓은 감시 = 핫(마지막 스캔 + 🔮 조짐 + 최근 움직임 상위, 약 1천) 매 회차 + 나머지 유니버스(초소형~소형주 전부) 회차마다 1,100종목씩 돌아가며
          — 1분봉 일괄 시세로 훑어 움직인 종목만 전체 계산
      (3) 공시 = EDGAR 최신 공시 피드로 넓은 감시 목록 전체."""
import sys, os, time, json, warnings
warnings.filterwarnings("ignore", category=FutureWarning); warnings.filterwarnings("ignore", category=DeprecationWarning); warnings.filterwarnings("ignore", module="yfinance")
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import db, params as P, live, alerts, scan, sources as src

def targets(c):
    """매번 전체 계산하는 핵심 대상: 관심종목 + '가능'·경보(flag) 종목 전부 + '대기' 점수순 (합계 max_tickers 까지, 가능·경보는 항상 포함)."""
    watch = db.get_setting("watchlist", ["SOUN", "OCGN"])
    df, _ = scan.last_scan()
    must, extra = [], []
    if len(df):
        d = df.sort_values("score", ascending=False)
        must = d[(d.status == "가능") | d.flagged.astype(bool)].ticker.tolist()
        extra = d[d.status == "대기"].ticker.tolist()
    first = list(dict.fromkeys(watch + must))
    return list(dict.fromkeys(first + extra))[: max(int(c.get("max_tickers", 25)), len(first))]

_WIDE = {}
HOT_N, COLD_N = 1000, 1100      # 매 회차 1분봉: 핫 목록 전부 + 나머지 유니버스 중 COLD_N 종목(돌아가며) → 전체는 몇 회차마다 한 바퀴

def wide_tiers(p=None, c=None):
    """급등 감시 대상 2단계 (하루 1번 계산해 캐시):
    hot = 마지막 스캔 전 종목 + 🔮 조짐 종목 + 유니버스 중 '최근 움직임'(5일 최대 등락·거래량 배수·거래대금) 상위 → 매 회차
    cold = 나머지 유니버스 전부 (거래대금 작은 종목 포함) → 회차마다 COLD_N 종목씩 돌아가며.
    반환: (hot, cold)."""
    key = time.strftime("%Y%m%d")
    if key in _WIDE: return _WIDE[key]
    p = p or P.load(); c = c or {}
    hot_n = int(c.get("hot_n", HOT_N))
    df, _ = scan.last_scan()
    hot = df.ticker.tolist() if len(df) else []
    try:
        from core import omen as OM
        hot += [r["ticker"] for r in ((OM.load_full() or {}).get("rows") or [])[:150]]
    except Exception:
        pass
    u = []
    try:
        import datetime as _dt, numpy as _np
        u = scan.universe(p).ticker.tolist()
        q = db.q("SELECT ticker, date, close, volume FROM prices WHERE date >= ? ORDER BY ticker, date",
                 ((_dt.date.today() - _dt.timedelta(days=45)).isoformat(),))
        us = set(u); heat = {}
        for t, g in q[q.ticker.isin(us)].groupby("ticker"):
            cl, v = g.close.values.astype(float), g.volume.values.astype(float)
            if len(cl) < 6: heat[t] = 1.0; continue       # 신규 상장 → 핫
            r5 = _np.nanmax(_np.abs(cl[-5:] / cl[-6:-1] - 1))
            vb = max(_np.median(v[-25:-5]) if len(v) > 10 else v.mean(), 1.0)
            vx = _np.nanmax(v[-5:]) / vb
            dv = float(_np.mean((cl * v)[-20:]))
            heat[t] = min(r5, 1.0) * 2 + min(vx, 10) / 10 + (0.3 if dv >= 1e6 else 0) + (0.2 if cl[-1] < 5 else 0)
        for t in u:
            heat.setdefault(t, 0.0)
        ranked = sorted(u, key=lambda t: -heat[t])
        hot = list(dict.fromkeys(hot + ranked))[: max(hot_n, len(set(hot)))]
    except Exception as e:
        print(f"넓은 감시 목록 실패: {type(e).__name__}: {str(e)[:80]}")
    hs = set(hot)
    cold = [t for t in u if t not in hs]
    _WIDE.clear(); _WIDE[key] = (hot, cold)
    return _WIDE[key]

def wide_set(p=None):
    """예전 호환: 감시 대상 전체 (핫 + 나머지)."""
    h, c_ = wide_tiers(p)
    return list(dict.fromkeys(h + c_))

def wide_slice(it, p=None, c=None):
    """이번 회차 1분봉 대상: 핫 전부 + 나머지 중 it 번째 조각. 반환 (대상, 핫 수, 나머지 수, 한 바퀴 회차 수)."""
    hot, cold = wide_tiers(p, c)
    n = int((c or {}).get("cold_n", COLD_N))
    k = max(1, -(-len(cold) // n)) if cold else 1
    i = it % k
    part = cold[i * n:(i + 1) * n]
    return list(dict.fromkeys(hot + part)), len(hot), len(cold), k

def prev_closes(tickers):
    """종목별 오늘(ET) 이전 마지막 일봉 종가 (DB) — 1차 선별의 등락률 기준."""
    import datetime as _dt
    from zoneinfo import ZoneInfo
    today = _dt.datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
    q = db.q("SELECT p.ticker, p.close, p.date FROM prices p JOIN (SELECT ticker, max(date) AS d FROM prices WHERE date < ? GROUP BY ticker) m "
             "ON p.ticker=m.ticker AND p.date=m.d", (today,))
    return {t: (float(c), str(d)[:10]) for t, c, d in zip(q.ticker, q.close, q.date)}

def prescreen(quotes, pcs, sess, c):
    """1분봉만으로 가볍게: 급등 알림 조건 근처(전일 대비 +10% 이상, 5분 +8% 이상, 프리 갭) 종목 → [(ticker, chg)] 큰 순."""
    import pandas as pd
    out = []
    lim = min(float(c.get("spike_chg", 15)), 10.0)
    for t, df in quotes.items():
        try:
            if df is None or len(df) == 0: continue
            last = float(df.close.iloc[-1]); age = (pd.Timestamp.now(tz=live.ET) - df.ts.iloc[-1]).total_seconds() / 60
            if age > 20: continue
            eh = live.ext_hours(df); ref = pcs.get(t)
            day = str(eh.get("day")); today = pd.Timestamp.now(tz=live.ET).strftime("%Y-%m-%d")
            if day != today: continue
            mp, md = eh.get("prev_close"), str(eh.get("prev_date") or "")
            ref = ref[0] if ref and (not mp or not md or ref[1] >= md) else mp     # 둘 중 더 최근 날짜 종가 (live.ref_close 와 같은 규칙)
            if not ref: continue
            chg = (last / ref - 1) * 100
            d = df[df.ts.dt.date == df.ts.dt.date.max()]
            up5 = (float(d.close.iloc[-1]) / float(d.close.tail(6).iloc[0]) - 1) * 100 if len(d) > 5 else 0
            if chg >= lim or (up5 >= 8 and chg >= 5) or (sess == "pre" and chg >= float(c.get("gap_min", 20))):
                out.append((t, chg))
        except Exception:
            continue
    return sorted(out, key=lambda z: -z[1])

def filing_targets(c, scan_rows=None):
    """공시 감시 대상: 관심종목 + 최근 스캔 점수 상위 + 최근 3일 알림 종목 (최대 filing_max)."""
    watch = db.get_setting("watchlist", ["SOUN", "OCGN"])
    df, _ = scan.last_scan()
    top = df.sort_values("score", ascending=False).ticker.head(60).tolist() if len(df) else []
    cut = time.time() - 3 * 86400
    rec = []
    for r in reversed(alerts.load_log()):
        try:
            if r.get("dry") or "filing" in (r.get("types") or []): continue
            import datetime as _dt
            if _dt.datetime.fromisoformat(r["ts_utc"]).timestamp() < cut: break
            rec.append(r["ticker"])
        except Exception:
            continue
    first = list(dict.fromkeys(watch + rec + targets(c)))
    return list(dict.fromkeys(first + top))[: max(int(c.get("filing_max", 55)), len(first))]

def db_424b(tickers):
    """DB 공시표에서 30일 내 424B (증자 설명서) → {ticker: 문구}."""
    out = {}
    try:
        import datetime as _dt
        q = db.q(f"SELECT ticker, max(filed) AS d, count(*) AS n FROM filings WHERE form LIKE '424B%' AND filed >= ? AND ticker IN ({','.join('?' * len(tickers))}) GROUP BY ticker",
                 ((_dt.date.today() - _dt.timedelta(days=30)).isoformat(), *tickers))
        for r in q.itertuples(): out[r.ticker] = f"424B 증자 설명서 {r.n}건 (30일 내, 최근 {str(r.d)[5:10].replace('-', '/')})"
    except Exception:
        pass
    return out

def run_filings(c, dry=False, wide=None, full=True):
    """full=True: 예전처럼 감시 목록 전부의 submissions 확인 (+ 피드). full=False: EDGAR 최신 공시 피드로 넓은 목록 중 새 공시가 있는 종목만."""
    from core import filings as F
    base = filing_targets(c) if full else list(dict.fromkeys(db.get_setting("watchlist", ["SOUN", "OCGN"]) + targets(c)))[:40]
    hit = set()
    if wide:
        try:
            hit, ferr = F.feed_tickers(wide)
            if ferr:
                print(f"공시 피드 오류 {ferr[:3]}")
                if not full: base = filing_targets(c)
        except Exception as e:
            print(f"공시 피드 실패: {type(e).__name__}: {str(e)[:80]}")
            if not full: base = filing_targets(c)
    order = {t: i for i, t in enumerate(wide or [])}        # 넓은 목록 앞쪽(핵심·핫) 우선, 한 회차 최대 filing_hit_max 종목
    hit_l = sorted(hit, key=lambda t: order.get(t, 1e9))[: int(c.get("filing_hit_max", 150))]
    tk = list(dict.fromkeys(base + hit_l))
    if hit: print(f"공시 피드: 넓은 감시 {len(wide)}종목 중 최근 공시 {len(hit)}종목")
    new, st = alerts.run_filings(tk, dry=dry, c=c, db_fil=db_424b(tk))
    for r in new:
        print(f"[{'전송' if r['sent'] else ('억제: ' + str(r['suppressed']) if r['suppressed'] else ('dry' if r['dry'] else '실패 ' + json.dumps(r['result'])))}] {r['title']} · {r['msgs'][0]}")
    print(f"공시: 대상 {st['tickers']} · 24h 공시 {st['found']} · 새로 판정 {st['new']} · 호재 {st['pos']} · 전송 {st['sent']} · 오류 {st['errs']} · {st.get('secs', 0)}s")
    return new

def borrow_step(tk):
    """IBKR 대차 파일(전 종목, 1~2초) 1회 → 대상 종목 DB 반영 + alert-data 브랜치에 최신/이력 CSV (앱·daily 가 읽음)."""
    if not src.ftp_allowed(): return
    try:
        uni = set(db.q("SELECT DISTINCT ticker FROM prices").ticker) | set(db.q("SELECT ticker FROM universe").ticker) | set(tk)
        n = src.store_borrow(list(uni))
        bdir = os.environ.get("SHORTDASH_BORROW_DIR")
        tot, ch = src.borrow_publish(bdir, uni) if bdir else (0, 0)
        print(f"대차(IBKR): DB {n}행 · 공개 스냅샷 {tot}종목 · 이력 추가 {ch}행 · 파일 시각 {src._IBKR.get('asof')} UTC")
    except Exception as e:
        print(f"대차 수집 실패: {type(e).__name__}: {str(e)[:120]}")

def once(force=False, dry=False, it=0, borrow_every=1, full_filings_every=1):
    """1회 스캔. it: 반복 번호 (반복 실행 시 대차·전체 공시 확인은 몇 번에 한 번만)."""
    t0 = time.time()
    sess = live.session_now()[0]
    c0 = alerts.cfg()
    core = targets(c0)
    if it % max(1, borrow_every) == 0: borrow_step(core)
    if sess == "closed" and not force:
        print("장 마감 시간 — 건너뜀 (--force 로 강제)")
        alerts.grade_all(); return []
    c = alerts.cfg(); p = P.load()
    tgt, n_hot, n_cold, cyc = wide_slice(it, p, c)
    wide = list(dict.fromkeys(core + tgt))
    quotes = live.batch_intraday(wide)            # 1분봉 일괄 (핫 전부 + 나머지 조각)
    for t in core:
        if t not in quotes: db.exec_("DELETE FROM kv WHERE k=?", (f"live1m:{t}",))     # 일괄에서 빠진 종목은 개별로 새로 받기
    tq = time.time()
    movers = [t for t, _ in prescreen({t: q for t, q in quotes.items() if t not in core}, prev_closes(list(quotes)), sess, c)]
    movers = movers[: int(c.get("max_movers", 25))]
    snaps = []
    for t in list(dict.fromkeys(core + movers)):
        try:
            snaps.append((t, live.snapshot(t, p, refresh_borrow=False)))
        except Exception as e:
            print(f"  {t}: 실패 {type(e).__name__}: {str(e)[:80]}")
    t1 = time.time()
    new = alerts.run(snaps, sess if sess != "closed" else "regular", dry=dry, c=c)
    try: new += run_filings(c, dry=dry, wide=list(dict.fromkeys(wide + wide_set(p))), full=(it % max(1, full_filings_every) == 0))   # 공시 피드는 유니버스 전체
    except Exception as e: print(f"공시 확인 실패: {type(e).__name__}: {str(e)[:120]}")
    t2 = time.time()
    alerts.grade_all()
    for r in new:
        print(f"[{'전송' if r['sent'] else ('억제: ' + str(r['suppressed']) if r['suppressed'] else ('dry' if r['dry'] else '실패 ' + json.dumps(r['result'])))}] {r['title']}")
    print(f"감시 단계: 핵심 {len(core)} + 핫 {n_hot} (매 회차) + 나머지 {n_cold} 중 {it % cyc + 1}/{cyc}번째 조각 ({cyc}회차마다 전체 한 바퀴)")
    print(f"세션 {sess} · 일괄 시세 {len(quotes)}/{len(wide)}종목 {tq - t0:.0f}s · 움직인 종목 {len(movers)} · 전체 계산 {len(snaps)} · 새 알림 {len(new)} · "
          f"{time.time() - t0:.0f}s (계산 {t1 - tq:.0f}s · 신호+공시 {t2 - t1:.0f}s)")
    return new

def session_loop(interval=150, max_min=330, sync=None, dry=False, until="regular"):
    """GitHub Actions 장중 반복: interval 초마다 once(), 프리마켓~정규장(until) 동안, 최대 max_min 분.
    반복마다 sync 명령(알림 기록 브랜치 pull/commit/push)을 실행. 반환: 'done'(장 끝) | 'handoff'(시간 한도 → 다음 작업에 넘김)."""
    import subprocess
    t_start, it = time.time(), 0
    okset = ("pre", "regular") if until == "regular" else ("pre", "regular", "post")
    while True:
        sess = live.session_now()[0]
        if sess not in okset: print(f"세션 {sess} — 반복 종료"); return "done"
        if (time.time() - t_start) / 60 > max_min: print("시간 한도 — 다음 작업에 넘김"); return "handoff"
        t0 = time.time()
        if sync: subprocess.run(sync + " pull", shell=True)
        try: once(dry=dry, it=it, borrow_every=6, full_filings_every=8)
        except Exception as e: print(f"오류: {type(e).__name__}: {str(e)[:200]}")
        if sync: subprocess.run(sync + " push", shell=True)
        it += 1
        took = time.time() - t0
        print(f"── {it}회차 {took:.0f}s · 다음까지 {max(5, interval - took):.0f}s", flush=True)
        time.sleep(max(5, interval - took))

if __name__ == "__main__":
    db.init()
    a = sys.argv
    if os.environ.get("GITHUB_ACTIONS"):
        c0 = alerts.cfg()
        if c0["channel"] in ("ntfy", "both") and not os.environ.get("NTFY_TOPIC"):
            print("::error::GitHub Secrets 에 NTFY_TOPIC 이 없습니다. 저장소 Settings → Secrets and variables → Actions 에서 추가하세요."); sys.exit(1)
    if "--test" in a:
        print("테스트 전송:", alerts.test()); sys.exit(0)
    if "--filings" in a:
        run_filings(alerts.cfg(), dry="--dry" in a); sys.exit(0)
    if "--grade" in a:
        alerts.grade_all(); print(alerts.forward_stats()); sys.exit(0)
    if "--session-loop" in a:
        iv = int(os.environ.get("LOOP_INTERVAL_S", "150")); mx = int(os.environ.get("LOOP_MAX_MIN", "330"))
        r = session_loop(iv, mx, sync=os.environ.get("ALERT_SYNC_CMD"), dry="--dry" in a)
        if os.environ.get("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"], "a") as fh: fh.write(f"result={r}\n")
        sys.exit(0)
    if "--loop" in a:
        mins = int(a[a.index("--loop") + 1])
        print(f"{mins}분마다 실행 (프리 04:00~애프터 20:00 ET). 이 창을 닫으면 멈춥니다.")
        it = 0
        while True:
            try: once(dry="--dry" in a, it=it, borrow_every=max(1, 15 // max(mins, 1)), full_filings_every=max(1, 20 // max(mins, 1)))
            except Exception as e: print("오류:", e)
            it += 1
            time.sleep(mins * 60)
    else:
        once(force="--force" in a, dry="--dry" in a)
