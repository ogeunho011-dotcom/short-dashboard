"""매일 1회 실행 (미국 장 마감 후, 한국시간 오전 7시경 권장).
python scripts/update_daily.py [--no-scan]"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import db, sources as src, params as P, scan

def price_freshness():
    """가격 최신일 점검: 가장 최근 날짜보다 뒤처진 종목은 5일치만 다시 받아봄 (빈 응답은 재시도)."""
    L = db.q("SELECT ticker, MAX(date) d FROM prices GROUP BY ticker")
    if not len(L): print("가격: 없음"); return
    top = L.d.max(); stale = L[L.d < top].ticker.tolist()
    print(f"가격 최신일 {top}: {len(L) - len(stale)}/{len(L)}종목 최신, 뒤처짐 {len(stale)}")
    recent = L[(L.d < top) & (L.d >= (__import__('pandas').Timestamp(top) - __import__('pandas').Timedelta(days=10)).strftime('%Y-%m-%d'))].ticker.tolist()
    if recent:
        n = src.bulk_prices(recent, "5d")
        L2 = db.q("SELECT ticker, MAX(date) d FROM prices GROUP BY ticker")
        print(f"  뒤처진 {len(recent)}종목 다시 받음 → {n}종목 응답, 이제 최신 {int((L2.d >= top).sum())}/{len(L2)}")
    # Yahoo 일봉은 장 마감 후 몇 시간 동안 마지막 날 종가가 비어 있음(NaN) → 1분봉으로 마지막 세션 막대를 만들어 채움.
    # 다음 날 실행 때 5일치 다시 받기로 공식 일봉이 덮어씀.
    import pandas as pd
    L2 = db.q("SELECT ticker, MAX(date) d FROM prices GROUP BY ticker")
    cut = (pd.Timestamp(top) - pd.Timedelta(days=10)).strftime("%Y-%m-%d")
    cand = L2[L2.d >= cut]
    last = dict(zip(cand.ticker, cand.d))
    B = src.bulk_today_bars(list(last), chunk=40)
    rows = [dict(ticker=t, date=b["date"].strftime("%Y-%m-%d"), open=b["open"], high=b["high"], low=b["low"], close=b["close"], volume=b["volume"])
            for t, b in B.items() if b["date"].strftime("%Y-%m-%d") > last[t] and b["close"] == b["close"]]
    if rows: db.upsert_df("prices", pd.DataFrame(rows), ["ticker", "date", "open", "high", "low", "close", "volume"])
    L3 = db.q("SELECT ticker, MAX(date) d FROM prices GROUP BY ticker"); top3 = L3.d.max()
    print(f"  1분봉으로 마지막 세션 채움: {len(rows)}종목 (1분봉 응답 {len(B)}/{len(last)}) → 최신일 {top3}: {int((L3.d >= top3).sum())}/{len(L3)}종목")

def main(do_scan=True):
    t0 = time.time()
    db.init()
    p = P.load()
    watch = db.get_setting("watchlist", ["SOUN", "OCGN"])
    n_u = src.fetch_universe()
    print(f"유니버스: {n_u}종목 · {src.universe_text()}")
    print("Threshold:", src.update_threshold(10))
    got, bad = src.update_finra(30, None)
    sv = db.q("SELECT MAX(date) d, COUNT(*) n FROM short_vol")
    last_n = db.q("SELECT COUNT(*) n FROM short_vol WHERE date=?", (sv.d.iloc[0],)).n.iloc[0] if len(sv) and sv.d.iloc[0] else 0
    print(f"FINRA RegSHO: 새로 {got:,}행, 실패 {bad}일 | 날짜별 소스: {src.finra_log_text()}")
    print(f"FINRA RegSHO DB: 최신 {sv.d.iloc[0]} ({last_n:,}종목), 전체 {sv.n.iloc[0]:,}행")
    print("FINRA 공매도 잔고 (최근 결제일):", src.update_finra_si(n_dates=4))
    print("대차 장중 이력 가져오기 (alert-data):", src.sync_borrow_remote(ttl=0, months=2))
    if src.ftp_allowed():
        print("대차 스냅샷 (IBKR):", src.store_borrow(list(set(db.q("SELECT DISTINCT ticker FROM prices").ticker) | set(db.q("SELECT ticker FROM universe").ticker))))
    for t in ["QQQ", "IWM"] + watch:
        src.fetch_prices(t, "2y")
    for t in watch:
        src.refresh_ticker(t); src.fetch_info(t, ttl=0)
        print("갱신:", t)
    src.update_ftd(3)
    if do_scan:
        ts_ = time.time()
        df = scan.run_scan(p)
        print(f"스캔: {len(df)}종목 정밀 · 일봉 갱신 {scan.PRICE_LOG} · 스캔 {time.time() - ts_:.0f}s")
        price_freshness()
        U = scan.universe(p).ticker.tolist()
        try:
            print("SEC 공시·재무 순환 갱신:", src.sec_rotate(U))
        except Exception as e:
            print("SEC 순환 갱신 실패:", repr(e)[:200])
        try:   # ⚠️ 참고 경고·💣 최신 공시 값용 공시 원문 (지난 조짐 종목 → $1 이하 → 스캔 상위 순, 시간 예산 안에서)
            from core import events as EV, omen as OM
            prev = [r["ticker"] for r in ((OM.load_full(24 * 7) or {}).get("rows") or [])]
            low = db.q("SELECT p.ticker FROM prices p JOIN (SELECT ticker, MAX(date) d FROM prices GROUP BY ticker) m ON p.ticker=m.ticker AND p.date=m.d "
                       "WHERE p.close <= 1 ORDER BY p.close").ticker.tolist()
            top = df.sort_values("score", ascending=False).ticker.head(150).tolist() if len(df) and "score" in df else []
            us = set(U); order = list(dict.fromkeys(t for t in prev + low + top if t in us))
            n, m, s_ = EV.refresh(order, budget_s=float(os.environ.get("EVENTS_BUDGET_S", 600)))
            print(f"⚠️ 공시 원문 해석 (참고 경고·최신 현금/주식 수): {n}/{m}종목 · {s_}s")
        except Exception as e:
            print("공시 원문 해석 실패:", repr(e)[:200])
        try:
            from core import omen as OM
            to = time.time(); k, m = OM.build_full()
            print(f"🔮 조짐 (유니버스 전체): {k}/{m}종목 · {time.time() - to:.0f}s")
        except Exception as e:
            print("🔮 조짐 전체 계산 실패:", repr(e)[:200])
        try:
            from core import secscan as SS
            m = SS.refresh(budget_s=float(os.environ.get("SEC_BUDGET_S", "420")))
            print(f"🔬 SEC 퀵스캔 (급등 후보): {m['n']}/{m['tried']}종목 · {m['secs']}s")
        except Exception as e:
            print("🔬 SEC 퀵스캔 실패:", repr(e)[:200])
        try:
            us = set(U)
            px_ = set(db.q("SELECT DISTINCT ticker FROM prices WHERE date >= date('now','-10 day')").ticker)
            sv = set(db.q("SELECT ticker FROM short_vol WHERE date=(SELECT MAX(date) FROM short_vol)").ticker)
            si = set(db.q("SELECT DISTINCT ticker FROM short_interest WHERE settle_date=(SELECT MAX(settle_date) FROM short_interest)").ticker)
            bo = set(db.q("SELECT DISTINCT ticker FROM borrow WHERE ts >= datetime('now','-3 day')").ticker)
            fk = set(db.q("SELECT k FROM kv WHERE k LIKE 'fil_ok:%'").k.str[7:])
            fx = set(db.q("SELECT k FROM kv WHERE k LIKE 'facts:%'").k.str[6:])
            print(f"커버리지 (유니버스 {len(us)}종목): 일봉(10일 내) {len(us & px_)} · FINRA 공매도량(최근일) {len(us & sv)} · 공매도 잔고(최근 결제일) {len(us & si)} · "
                  f"IBKR 대차(3일 내) {len(us & bo)} · SEC 공시 확인 {len(us & fk)} · SEC 재무 {len(us & fx)}")
        except Exception as e:
            print("커버리지 집계 실패:", repr(e)[:160])
        try:
            from core import closebet as CB
            n, m = CB.cloud_prefetch(150)
            print(f"종가 베팅 1분봉 저장: {n}/{m}종목 (재시도 {src.YF_LOG.get('retries', 0)}회)")
        except Exception as e:
            print("종가 베팅 1분봉 저장 실패:", repr(e)[:200])
    print(f"완료 {time.time() - t0:.0f}s")
    print(db.q("SELECT name, ok, msg FROM source_status").to_string())

if __name__ == "__main__":
    main("--no-scan" not in sys.argv)
