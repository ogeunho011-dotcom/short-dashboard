"""매일 1회 실행 (미국 장 마감 후, 한국시간 오전 7시경 권장).
python scripts/update_daily.py [--no-scan]"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import db, sources as src, params as P, scan

def main(do_scan=True):
    t0 = time.time()
    db.init()
    p = P.load()
    watch = db.get_setting("watchlist", ["SOUN", "OCGN"])
    print("유니버스:", src.fetch_universe())
    print("Threshold:", src.update_threshold(10))
    print("FINRA (차단 시 자동 중단):", src.update_finra(30, None))
    for t in ["QQQ", "IWM"] + watch:
        src.fetch_prices(t, "2y")
    for t in watch:
        src.refresh_ticker(t); src.fetch_info(t, ttl=0)
        print("갱신:", t)
    src.update_ftd(3)
    if do_scan:
        df = scan.run_scan(p)
        print("스캔:", len(df))
    print(f"완료 {time.time() - t0:.0f}s")
    print(db.q("SELECT name, ok, msg FROM source_status").to_string())

if __name__ == "__main__":
    main("--no-scan" not in sys.argv)
