"""토스증권 링크: 티커 → 토스 상품코드(예: SOUN → US20220428003) 매핑 + 앱/웹 링크.

확인한 사실 (2026-10-28):
- 웹 종목 페이지:  https://www.tossinvest.com/stocks/<상품코드>/order  (PC 크롬/엣지용. 폰 브라우저는 '지원하지 않는 브라우저' 안내)
- 모바일 웹:       https://contents.tossinvest.com/stocks/<상품코드>   ('앱에서 보기' 버튼)
- 앱 열기: 토스증권 웹이 스스로 쓰는 방식 =
  supertoss://securities?url=<enc(https://service.tossinvest.com?nextLandingUrl=<enc(/stocks/코드)>)>
  이를 AppsFlyer OneLink(https://toss.onelink.me/3563614660) 로 감싸면, 앱이 있으면 앱, 없으면 웹으로 이동.
- 티커 → 코드: 공개(비공식) API  https://wts-info-api.tossinvest.com/api/v2/stock-infos/code-or-symbol/<TICKER>
  (실패 시 자동완성 API → 그래도 실패면 토스증권 홈으로 대체; 검색 URL은 공개 경로가 없음)
비공식 엔드포인트라 토스가 바꾸면 깨질 수 있음 → 결과는 DB(kv)에 30일 캐시."""
import re, os, json
from urllib.parse import quote
from concurrent.futures import ThreadPoolExecutor
import requests
from . import db

_H = {"User-Agent": "Mozilla/5.0", "Origin": "https://www.tossinvest.com", "Referer": "https://www.tossinvest.com/"}
_MEM = {}
TTL = 30 * 86400
SEED = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "toss_codes.json")

def _seed():
    """저장소에 같이 올리는 매핑 파일(data/toss_codes.json) — 클라우드에서 첫 로딩을 빠르게."""
    if "_seed" not in _MEM:
        try: _MEM["_seed"] = json.load(open(SEED, encoding="utf-8"))
        except Exception: _MEM["_seed"] = {}
    return _MEM["_seed"]

def _lookup(t):
    try:
        r = requests.get(f"https://wts-info-api.tossinvest.com/api/v2/stock-infos/code-or-symbol/{t}", headers=_H, timeout=8)
        j = (r.json() or {}).get("result") if r.ok else None
        if j and (j.get("symbol") or "").upper() == t and j.get("code"):
            return {"code": j["code"], "name": j.get("name"), "market": (j.get("market") or {}).get("code")}
    except Exception:
        pass
    try:
        r = requests.post("https://wts-info-api.tossinvest.com/api/v3/search-all/wts-auto-complete", headers=dict(_H, **{"Content-Type": "application/json"}),
                          json={"query": t, "sections": [{"type": "PRODUCT", "option": {"addIntegratedSearchResult": True}}]}, timeout=8)
        for sec in (r.json() or {}).get("result") or []:
            for it in ((sec.get("data") or {}).get("items") or []):
                if (it.get("symbol") or "").upper() == t and it.get("productCode"):
                    return {"code": it["productCode"], "name": it.get("productName"), "market": it.get("market")}
    except Exception:
        pass
    return None

def code(ticker, network=True):
    """티커 → 토스 상품코드. 캐시(메모리 → DB 30일) 우선, network=False 면 캐시만."""
    t = re.sub(r"[^A-Z0-9.\-]", "", str(ticker).upper())
    if not t: return None
    if t in _MEM: return _MEM[t]
    if _seed().get(t):
        _MEM[t] = _seed()[t]; return _MEM[t]
    c = db.kv_get(f"toss:{t}", TTL)
    if c is not None and not c.get("code"):
        c = db.kv_get(f"toss:{t}", 86400)          # 매핑 실패는 하루만 캐시
    if c is not None:
        _MEM[t] = c.get("code"); return _MEM[t]
    if not network: return None
    info = _lookup(t)
    db.kv_set(f"toss:{t}", info or {"code": None})   # 실패도 캐시 (30일 뒤 재시도)
    _MEM[t] = (info or {}).get("code"); return _MEM[t]

def web_url(ticker, c=None):
    c = c or code(ticker)
    # 매핑 실패 시: 토스 검색 페이지 URL은 공개 경로가 없어(404) 토스증권 홈으로 보냄 (검증 안 된 대체)
    return f"https://www.tossinvest.com/stocks/{c}/order" if c else "https://www.tossinvest.com/"

def mobile_web_url(ticker, c=None):
    c = c or code(ticker)
    return f"https://contents.tossinvest.com/stocks/{c}" if c else web_url(ticker, c)

def app_scheme(ticker, c=None):
    c = c or code(ticker)
    path = f"/stocks/{c}" if c else "/"
    inner = "https://service.tossinvest.com?nextLandingUrl=" + quote(path, safe="")
    return "supertoss://securities?url=" + quote(inner, safe="") + "&clearHistory=true&swipeRefresh=true"

def onelink(ticker, c=None):
    c = c or code(ticker)
    return ("https://toss.onelink.me/3563614660?af_dp=" + quote(app_scheme(ticker, c), safe="") +
            "&af_web_dp=" + quote(mobile_web_url(ticker, c), safe=""))

MODES = {"onelink": "앱 우선 (없으면 웹) — 권장", "scheme": "앱 바로 열기 (supertoss://)", "web": "웹 (PC 토스증권)"}

def url(ticker, mode=None, network=True):
    """설정(관리 탭) 모드에 맞는 링크. 코드 매핑 실패해도 항상 열 수 있는 링크를 돌려줌."""
    mode = mode or db.get_setting("toss_mode", "onelink")
    c = code(ticker, network=network)
    if mode == "web": return web_url(ticker, c)
    if mode == "scheme": return app_scheme(ticker, c)
    return onelink(ticker, c)

def prefetch(tickers, workers=8):
    """화면에 나올 티커들을 병렬로 미리 매핑 (처음 1회만 몇 초, 이후 캐시)."""
    todo = [t for t in dict.fromkeys(str(x).upper() for x in tickers) if t and t not in _MEM and not _seed().get(t)]
    todo = [t for t in todo if db.kv_get(f"toss:{t}", TTL) is None]
    if todo:
        with ThreadPoolExecutor(workers) as ex:
            res = list(ex.map(lambda t: (t, _lookup(t)), todo))
        for t, info in res:          # DB 쓰기는 메인 스레드에서
            db.kv_set(f"toss:{t}", info or {"code": None}); _MEM[t] = (info or {}).get("code")
    return {t: code(t, network=False) for t in tickers}

def verify(c):
    """상품코드가 실제 토스 종목인지 확인 (stock-infos API)."""
    try:
        r = requests.get(f"https://wts-info-api.tossinvest.com/api/v2/stock-infos?codes={c}", headers=_H, timeout=8)
        res = (r.json() or {}).get("result") or []
        return r.status_code, (res[0].get("symbol"), res[0].get("name")) if res else None
    except Exception as e:
        return None, str(e)

def build_seed(tickers, workers=8):
    m = prefetch(tickers, workers)
    out = {t: c for t, c in m.items() if c}
    json.dump(dict(sorted(out.items())), open(SEED, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    return len(out), len(m)
