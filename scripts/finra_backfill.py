"""FINRA Reg SHO 일별 공매도 거래량 백필 (CNMS 통합 파일, 무료 공개 CDN)."""
import sys, datetime as dt, time
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, ".")
from core import sources as src, db
tick = list(db.q("SELECT DISTINCT ticker FROM prices")["ticker"])
have = set(db.q("SELECT date FROM finra_days WHERE status='ok'")["date"])
start = dt.date.fromisoformat(sys.argv[1] if len(sys.argv) > 1 else "2025-03-01")
end = dt.date.fromisoformat(sys.argv[2] if len(sys.argv) > 2 else "2026-10-27")
days = [start + dt.timedelta(i) for i in range((end - start).days + 1)]
days = [d for d in days if d.weekday() < 5 and d.strftime("%Y%m%d") not in have]
print(len(tick), "tickers", len(days), "days", flush=True)
def go(d):
    for a in range(3):
        n = src.fetch_finra_day(d, tick)
        if n >= 0: return d, n
        time.sleep(2 + a * 3)
    return d, n
tot = 0
with ThreadPoolExecutor(3) as ex:
    for i, (d, n) in enumerate(ex.map(go, days)):
        tot += max(n, 0)
        if i % 25 == 0: print(i, d, n, tot, flush=True)
print("done", tot)
