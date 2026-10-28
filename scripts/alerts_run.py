"""급등 신호 알림 스캐너 (PC 반복 실행 · GitHub Actions 1회 실행 공용).

  python scripts/alerts_run.py              # 1회 (장 마감 시간이면 건너뜀)
  python scripts/alerts_run.py --loop 10    # 10분마다 반복 (프리·정규·애프터 시간에만)
  python scripts/alerts_run.py --force      # 장 시간 무시하고 1회
  python scripts/alerts_run.py --test       # 테스트 알림만 전송
  python scripts/alerts_run.py --dry        # 판정만, 전송 안 함
  python scripts/alerts_run.py --grade      # 지난 알림 채점만
  python scripts/alerts_run.py --filings --dry   # 공시 판정만 (전송 안 함)
  (테스트용 다른 주제: 환경변수 NTFY_TOPIC 을 임시 주제로)

대상: 관심종목 + 최근 스크리너의 '가능/대기' 상위(점수순) — 관리 탭 '알림 대상 최대 종목 수'."""
import sys, os, time, json, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import db, params as P, live, alerts, scan

def targets(c):
    watch = db.get_setting("watchlist", ["SOUN", "OCGN"])
    df, _ = scan.last_scan()
    extra = []
    if len(df):
        d = df[df.status.isin(["가능", "대기"]) | df.flagged.astype(bool)].sort_values("score", ascending=False)
        extra = d.ticker.tolist()
    return list(dict.fromkeys(watch + extra))[: int(c.get("max_tickers", 25))]

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

def run_filings(c, dry=False):
    tk = filing_targets(c)
    new, st = alerts.run_filings(tk, dry=dry, c=c, db_fil=db_424b(tk))
    for r in new:
        print(f"[{'전송' if r['sent'] else ('억제: ' + str(r['suppressed']) if r['suppressed'] else ('dry' if r['dry'] else '실패 ' + json.dumps(r['result'])))}] {r['title']} · {r['msgs'][0]}")
    print(f"공시: 대상 {st['tickers']} · 24h 공시 {st['found']} · 새로 판정 {st['new']} · 호재 {st['pos']} · 전송 {st['sent']} · 오류 {st['errs']} · {st.get('secs', 0)}s")
    return new

def once(force=False, dry=False):
    t0 = time.time()
    sess = live.session_now()[0]
    if sess == "closed" and not force:
        print("장 마감 시간 — 건너뜀 (--force 로 강제)")
        alerts.grade_all(); return []
    c = alerts.cfg(); p = P.load()
    snaps = []
    for t in targets(c):
        db.exec_("DELETE FROM kv WHERE k=?", (f"live1m:{t}",))     # 1분봉 새로 받기
        try:
            snaps.append((t, live.snapshot(t, p, refresh_borrow=False)))
        except Exception as e:
            print(f"  {t}: 실패 {type(e).__name__}: {str(e)[:80]}")
    t1 = time.time()
    new = alerts.run(snaps, sess if sess != "closed" else "regular", dry=dry, c=c)
    try: new += run_filings(c, dry=dry)
    except Exception as e: print(f"공시 확인 실패: {type(e).__name__}: {str(e)[:120]}")
    t2 = time.time()
    alerts.grade_all()
    for r in new:
        print(f"[{'전송' if r['sent'] else ('억제: ' + str(r['suppressed']) if r['suppressed'] else ('dry' if r['dry'] else '실패 ' + json.dumps(r['result'])))}] {r['title']}")
    print(f"세션 {sess} · 종목 {len(snaps)} · 새 알림 {len(new)} · {time.time() - t0:.0f}s (시세 {t1 - t0:.0f}s · 신호+공시 {t2 - t1:.0f}s)")
    return new

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
    if "--loop" in a:
        mins = int(a[a.index("--loop") + 1])
        print(f"{mins}분마다 실행 (프리 04:00~애프터 20:00 ET). 이 창을 닫으면 멈춥니다.")
        while True:
            try: once(dry="--dry" in a)
            except Exception as e: print("오류:", e)
            time.sleep(mins * 60)
    else:
        once(force="--force" in a, dry="--dry" in a)
