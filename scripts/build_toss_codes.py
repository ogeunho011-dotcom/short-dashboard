"""유니버스 전체 티커 → 토스 상품코드 매핑.
python scripts/build_toss_codes.py            : data/toss_codes.json 새로 만들기 (저장소에 같이 올리는 파일)
python scripts/build_toss_codes.py --new-only : 파일에 없는 새 종목만 조회해 DB 캐시에 저장 (GitHub Actions daily 용)"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import db, toss
db.init()
ts = db.q("SELECT ticker FROM universe")["ticker"].tolist()
t0 = time.time()
if "--new-only" in sys.argv:
    m = toss.prefetch(ts)
    print(f"toss codes cached: {sum(1 for v in m.values() if v)}/{len(m)} in {time.time()-t0:.0f}s")
else:
    ok, n = toss.build_seed(ts)
    print(f"toss codes: {ok}/{n} mapped in {time.time()-t0:.0f}s -> {toss.SEED}")
