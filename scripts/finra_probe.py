"""FINRA RegSHO 소스 점검 (DB 안 씀): 최근 평일 하루에 대해 CDN·API 응답 코드와 행 수를 출력.
python scripts/finra_probe.py [YYYY-MM-DD]"""
import sys, datetime as dt, requests
sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__))))
from core.sources import FINRA_URL, FINRA_API, FINRA_HDR, UA_BROWSER

d = dt.date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else dt.date.today() - dt.timedelta(days=1)
while d.weekday() >= 5: d -= dt.timedelta(days=1)
print("점검 날짜:", d)
for nm, hd in (("CDN(브라우저 헤더)", FINRA_HDR), ("CDN(curl UA)", {"User-Agent": "curl/8.5.0"})):
    try:
        r = requests.get(FINRA_URL.format(d=d.strftime("%Y%m%d")), headers=hd, allow_redirects=False, timeout=30)
        rows = r.text.count("\n") - 1 if r.status_code == 200 and r.text.startswith("Date|") else 0
        print(f"{nm}: HTTP {r.status_code}, {rows:,}행" + (f", Location={r.headers.get('Location')}" if r.is_redirect else ""))
    except Exception as e:
        print(f"{nm}: 오류 {e!r}")
try:
    r = requests.post(FINRA_API, json={"limit": 5000, "offset": 0, "compareFilters": [{"compareType": "equal", "fieldName": "tradeReportDate", "fieldValue": d.isoformat()}]},
                      headers={"Accept": "application/json", "Content-Type": "application/json", "User-Agent": UA_BROWSER}, timeout=60)
    print(f"API: HTTP {r.status_code}, 첫 페이지 {len(r.json()) if r.status_code == 200 else 0:,}행 (5000개씩)")
except Exception as e:
    print(f"API: 오류 {e!r}")
