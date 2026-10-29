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

def main(do_scan=True):
    t0 = time.time()
    db.init()
    p = P.load()
    watch = db.get_setting("watchlist", ["SOUN", "OCGN"])
    print("유니버스:", src.fetch_universe())
    print("Threshold:", src.update_threshold(10))
    got, bad = src.update_finra(30, None)
    sv = db.q("SELECT MAX(date) d, COUNT(*) n FROM short_vol")
    last_n = db.q("SELECT COUNT(*) n FROM short_vol WHERE date=?", (sv.d.iloc[0],)).n.iloc[0] if len(sv) and sv.d.iloc[0] else 0
    print(f"FINRA RegSHO: 새로 {got:,}행, 실패 {bad}일 | 날짜별 소스: {src.finra_log_text()}")
    print(f"FINRA RegSHO DB: 최신 {sv.d.iloc[0]} ({last_n:,}종목), 전체 {sv.n.iloc[0]:,}행")
    print("FINRA 공매도 잔고 (최근 결제일):", src.update_finra_si(n_dates=4))
    print("대차 장중 이력 가져오기 (alert-data):", src.sync_borrow_remote(ttl=0, months=2))
    if src.ftp_allowed():
        print("대차 스냅샷 (IBKR):", src.store_borrow(list(set(db.q("SELECT DISTINCT ticker FROM prices").ticker))))
    for t in ["QQQ", "IWM"] + watch:
        src.fetch_prices(t, "2y")
    for t in watch:
        src.refresh_ticker(t); src.fetch_info(t, ttl=0)
        print("갱신:", t)
    src.update_ftd(3)
    if do_scan:
        df = scan.run_scan(p)
        print("스캔:", len(df))
        price_freshness()
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
