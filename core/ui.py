"""HTML/CSS 컴포넌트 (다크 테마, 한국 주식 커뮤니티 스타일)."""
import html as _h
import math

CSS = """
<style>
/* 홈 카드 (위계: 티커 → 확률 → 한 줄 요약 → 핵심 가격) */
.hc { display:block; text-decoration:none !important; color:inherit !important; -webkit-tap-highlight-color:transparent; }
.hc .card { padding:16px; margin:10px 0; }
.hc .t1 { display:flex; justify-content:space-between; align-items:flex-start; gap:10px; }
.hc .sym { font-size:24px; font-weight:900; letter-spacing:-0.5px; line-height:1.1; }
.hc .nm { color:var(--muted); font-size:12px; margin-top:2px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; max-width:52vw; }
.hc .pr { text-align:right; } .hc .pr .v { font-size:20px; font-weight:800; line-height:1.15; } .hc .pr .c { font-size:13px; font-weight:700; }
.hc .pb { margin-top:12px; display:flex; align-items:center; gap:10px; }
.hc .pb .pv { font-size:28px; font-weight:900; letter-spacing:-0.8px; min-width:64px; }
.hc .pb .pl { flex:1; min-width:0; } .hc .pb .pl .lab { color:var(--muted); font-size:12px; }
.hc .meter { height:6px; border-radius:6px; background:#262c3a; margin-top:5px; overflow:hidden; } .hc .meter > div { height:100%; border-radius:6px; background:linear-gradient(90deg,#fcd34d,#ff4d5e); }
.hc .sumline { font-size:14px; line-height:1.5; color:#e8eaf0; margin-top:12px; }
.lv3 { display:grid; grid-template-columns:repeat(3, minmax(0,1fr)); gap:8px; margin-top:12px; }
.lv3 .box { padding:8px; min-height:56px; } .lv3 .lab { font-size:11px; } .lv3 .val { font-size:15px; } 
.hc .foot { margin-top:10px; }
/* 로딩 스켈레톤 */
.skel { background:var(--card); border:1px solid var(--line); border-radius:16px; padding:16px; margin:10px 0; }
.skel .ln { height:14px; border-radius:7px; margin:8px 0; background:linear-gradient(90deg,#1b2030 0%,#262d40 50%,#1b2030 100%); background-size:200% 100%; animation: shimmer 1.2s infinite linear; }
@keyframes shimmer { 0% { background-position:200% 0; } 100% { background-position:-200% 0; } }
@import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css');
html, body, [class*="css"], .stMarkdown, .stText, button, input { font-family: Pretendard, -apple-system, 'Apple SD Gothic Neo', 'Noto Sans KR', sans-serif !important; }
html, body { overflow-x:hidden !important; max-width:100vw; -webkit-text-size-adjust:100%; overscroll-behavior-y:none; }
[data-testid="stAppViewContainer"], [data-testid="stMain"], .main { overflow-x:hidden !important; }
.block-container { padding: calc(0.5rem + env(safe-area-inset-top)) max(0.6rem, env(safe-area-inset-right)) calc(5.6rem + env(safe-area-inset-bottom)) max(0.6rem, env(safe-area-inset-left)) !important; max-width: 760px; }
/* Streamlit 기본 UI(메뉴·헤더·푸터·배포 버튼·상태 위젯) 숨김 → 앱처럼 보이게 */
header[data-testid="stHeader"], #MainMenu, footer, [data-testid="stToolbar"], [data-testid="stDecoration"], [data-testid="stStatusWidget"],
.stDeployButton, [data-testid="stAppDeployButton"], [data-testid="stMainMenu"], .viewerBadge_container__1QSob, [class*="viewerBadge"], [data-testid="manage-app-button"] { display:none !important; visibility:hidden !important; }
[data-testid="stVerticalBlock"] { gap:0.45rem; }
[data-testid="stElementContainer"]:has(iframe[height="0"]), .element-container:has(iframe[height="0"]) { display:none !important; }
.stButton button, .stDownloadButton button, [data-testid="stBaseButton-secondary"], [data-testid="stBaseButton-primary"] { min-height:44px; border-radius:12px; font-weight:700; }
[data-testid="stExpander"] summary { min-height:46px; display:flex; align-items:center; font-weight:700; }
[data-testid="stExpander"] details { border-radius:14px; border-color:var(--line); background:var(--card); }
.stTabs [data-baseweb="tab"] { min-height:42px; padding:0 10px; }
.stTextInput input, .stNumberInput input, [data-baseweb="select"] > div { min-height:44px; font-size:16px !important; }
[data-testid="stDataFrame"], .stTable, table { max-width:100%; }
.card, .grid, .chips { max-width:100%; overflow-wrap:anywhere; }
.sec { font-weight:800; font-size:15px; margin:14px 2px 2px 2px; }
* { -webkit-tap-highlight-color: rgba(255,77,94,0.15); }
:root { --red:#ff4d5e; --red2:#3a1218; --green:#22c55e; --green2:#0f2a1a; --card:#151923; --card2:#1c2130; --line:#2a3142; --muted:#8b93a7; --yellow:#fbbf24; --blue:#60a5fa; }
.topbar { display:flex; align-items:center; justify-content:space-between; margin:2px 0 8px 0; }
.brand { font-weight:800; font-size:17px; letter-spacing:-0.3px; }
.brand small { color:var(--muted); font-weight:500; font-size:11px; margin-left:6px; }
.card { background:var(--card); border:1px solid var(--line); border-radius:16px; padding:14px; margin:8px 0; }
.card.rc { background:linear-gradient(160deg,#3b0f17 0%, #1d0b10 100%); border-color:#5a1a24; }
.card.gc { background:linear-gradient(160deg,#0f2d1c 0%, #0b1a12 100%); border-color:#1d4a30; }
.card h3 { margin:0 0 6px 0; font-size:15px; font-weight:800; }
.muted { color:var(--muted); font-size:12px; }
.tiny { color:var(--muted); font-size:11.5px; line-height:1.45; }
.red { color:var(--red); } .green { color:var(--green); } .yellow { color:var(--yellow); } .blue { color:var(--blue); }
.big { font-size:30px; font-weight:800; letter-spacing:-0.8px; line-height:1.1; }
.mid { font-size:20px; font-weight:800; letter-spacing:-0.4px; }
.row { display:flex; gap:8px; } .row > * { flex:1; }
.between { display:flex; justify-content:space-between; align-items:center; gap:8px; }
.box { background:rgba(255,255,255,0.04); border:1px solid var(--line); border-radius:12px; padding:9px 10px; }
.box .lab { color:var(--muted); font-size:11px; } .box .val { font-size:16px; font-weight:800; margin-top:2px; }
.badge { display:inline-block; padding:2px 8px; border-radius:999px; font-size:11px; font-weight:700; background:#2a3142; color:#cbd5e1; margin-right:4px; }
.badge.red { background:#4a1520; color:#ff8a95; } .badge.green { background:#123821; color:#6ee7a0; } .badge.yellow { background:#3d3210; color:#fcd34d; }
.badge.live { background:#ff4d5e; color:white; animation: pulse 1.6s infinite; }
@keyframes pulse { 0%{opacity:1} 50%{opacity:.55} 100%{opacity:1} }
.bar { height:8px; background:#262c3b; border-radius:99px; overflow:hidden; margin:6px 0 3px 0; }
.bar > div { height:100%; border-radius:99px; background:linear-gradient(90deg,#ff4d5e,#ff9a62); }
.bar.g > div { background:linear-gradient(90deg,#16a34a,#4ade80); }
.prob { text-align:center; }
.prob .pct { font-size:44px; font-weight:900; letter-spacing:-1.5px; }
.carousel { display:flex; overflow-x:auto; scroll-snap-type:x mandatory; gap:10px; padding-bottom:6px; -webkit-overflow-scrolling:touch; scrollbar-width:none; }
.carousel::-webkit-scrollbar { display:none; }
.carousel > .card { flex:0 0 90%; max-width:520px; scroll-snap-align:center; margin:4px 0; }
.dots { text-align:center; color:var(--muted); font-size:11px; margin-top:-2px; }
.bpbox { background:rgba(56,189,248,0.07); border:1px solid rgba(56,189,248,0.35); border-radius:12px; padding:10px 11px; }
.bpbox .bpp { font-size:26px; font-weight:900; color:#38bdf8; margin:2px 0 8px; } .bpbox .ev2 { font-size:12.5px; line-height:1.5; margin:2px 0; }
.bpbox details summary { cursor:pointer; margin-top:6px; color:#94a3b8; }
.ev { display:flex; gap:8px; padding:5px 0; border-bottom:1px dashed #262c3b; font-size:12.5px; }
.ev .n { flex:0 0 20px; height:20px; border-radius:50%; background:#2a3142; text-align:center; font-size:11px; line-height:20px; font-weight:700; }
.ev .d { color:var(--muted); flex:0 0 46px; font-size:11px; padding-top:2px; }
.tr { border-left:4px solid var(--line); padding:8px 10px; margin:6px 0; background:var(--card2); border-radius:10px; }
.tr.profit { border-left-color: var(--green); } .tr.loss { border-left-color: var(--red); } .tr.mixed { border-left-color: var(--yellow); }
.band { display:grid; grid-template-columns: 92px 1fr 64px 58px; gap:6px; align-items:center; font-size:11.5px; padding:2px 0; }
.band .bg { height:12px; background:#262c3b; border-radius:3px; position:relative; overflow:hidden; }
.band .fg { position:absolute; left:0; top:0; bottom:0; border-radius:3px; }
.mark { border-top:1.5px dashed; margin:3px 0; font-size:10.5px; padding-top:1px; }
.gapbox { border:1px dashed #475069; border-radius:10px; padding:8px 10px; font-size:12px; color:#cbd5e1; margin:6px 0; background:rgba(96,165,250,0.06); }
.chips { display:flex; flex-wrap:wrap; gap:6px; margin:6px 0; }
.chip { background:var(--card2); border:1px solid var(--line); border-radius:999px; padding:5px 10px; font-size:12px; }
.chip.on { border-color:var(--red); color:#ffb3ba; }
.grid { display:grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap:7px; margin-bottom:12px; }
.sum { font-size:12.5px; line-height:1.4; color:#d6dbe6; margin-top:5px; max-height:4.2em; overflow:hidden; }
.sumbig { font-size:14px; line-height:1.45; font-weight:700; color:#fff; background:rgba(255,255,255,0.06); border-radius:10px; padding:8px 10px; margin-top:10px; }
.tk { background:var(--card2); border:1px solid var(--line); border-radius:12px; padding:8px; text-decoration:none !important; color:inherit !important; display:block; }
.tk .no { color:var(--muted); font-size:10px; } .tk .sym { font-weight:800; font-size:14px; } .tk .st { font-size:11px; font-weight:700; }
.tk.ok { border-color:#5a1a24; background:linear-gradient(160deg,#2d0e14,#1a0c10); }
.nav { position:fixed; bottom:0; left:0; right:0; z-index:9999; background:rgba(12,14,20,0.97); backdrop-filter:blur(8px); border-top:1px solid var(--line); display:flex; overflow:hidden; padding:4px 4px calc(4px + env(safe-area-inset-bottom)) 4px; }
.nav::-webkit-scrollbar { display:none; }
.nav a { flex:1 1 0; min-width:0; min-height:52px; display:flex; flex-direction:column; align-items:center; justify-content:center; text-align:center; color:#8b93a7 !important; text-decoration:none !important; font-size:11px; padding:2px 0; white-space:nowrap; border-radius:12px; -webkit-tap-highlight-color:transparent; }
.nav a:active { background:rgba(255,255,255,0.06); }
.nav a .i { display:block; font-size:21px; line-height:26px; }
.nav a.act { color:#ff6b78 !important; font-weight:700; }
.ladder { position:relative; height:440px; margin:6px 0 4px 0; border-left:1px solid #2a3142; margin-left:46px; }
.ladder .tb { position:absolute; left:6px; right:8px; border-radius:7px; font-size:10.5px; padding:2px 6px; overflow:hidden; color:#fff; }
.ladder .ln { position:absolute; left:-46px; right:0; border-top:1.5px dashed; font-size:10px; }
.ladder .ln span { position:absolute; left:0; top:-9px; background:#151923; padding:0 3px; line-height:18px; font-size:12px; }
.ladder .ln b { position:absolute; right:0; top:-9px; font-weight:600; background:#151923cc; padding:0 4px; border-radius:4px; line-height:18px; font-size:12px; z-index:3; }
.ladder .bz { position:absolute; left:0; right:0; background:repeating-linear-gradient(45deg, rgba(96,165,250,.18) 0 6px, rgba(96,165,250,.06) 6px 12px); border:1px solid rgba(96,165,250,.5); }
table.t { width:100%; border-collapse:collapse; font-size:12px; }
table.t th { color:var(--muted); font-weight:600; text-align:right; padding:4px 3px; border-bottom:1px solid var(--line); }
table.t td { text-align:right; padding:4px 3px; border-bottom:1px solid #1f2432; }
table.t th:first-child, table.t td:first-child { text-align:left; }
.disc { color:#6b7280; font-size:10.5px; text-align:center; margin:14px 0 4px 0; line-height:1.45; }
div[data-testid="stTextInput"] input { background:#151923; border-radius:12px; }
.stTabs [data-baseweb="tab"] { font-weight:700; }
/* 토스증권 바로가기 */
.tsb { display:inline-flex; align-items:center; gap:2px; font-size:11px; font-weight:800; color:#fff !important; background:#3182f6; border-radius:999px; padding:2px 8px; text-decoration:none !important; position:relative; z-index:3; vertical-align:middle; margin-left:6px; line-height:1.5; white-space:nowrap; }
.tsb:active { filter:brightness(0.85); }
.tsb.big { font-size:14px; padding:8px 14px; border-radius:12px; margin:4px 0; }
.hc, .tk { position:relative; }
.hc .ov, .tk .ov { position:absolute; inset:0; z-index:2; border-radius:12px; }
.hc .t1 .sym .tsb { font-size:12px; }
</style>
"""

NAV = [("home", "🏠", "홈·선별"), ("stock", "📈", "종목"), ("live", "⚡", "실시간"), ("track", "⏳", "타임머신"), ("admin", "⚙️", "관리")]

def esc(x): return _h.escape(str(x))

def nav(active, ticker=None):
    q = f"&t={ticker}" if ticker else ""
    return '<div class="nav">' + "".join(f'<a href="?p={k}{q}" target="_self" class="{"act" if k == active else ""}"><span class="i">{i}</span>{n}</a>' for k, i, n in NAV) + "</div>"

def px(v):
    if v is None or (isinstance(v, float) and math.isnan(v)): return "N/A"
    v = float(v)
    if v < 1: return f"${v:.4f}".rstrip("0").rstrip(".") if v < 0.1 else f"${v:.3f}"
    if v < 10: return f"${v:.2f}"
    return f"${v:,.2f}"

def pct(v, d=1, sign=True):
    if v is None or (isinstance(v, float) and math.isnan(v)): return "N/A"
    return f"{v:+.{d}f}%" if sign else f"{v:.{d}f}%"

def num(v):
    if v is None or (isinstance(v, float) and math.isnan(v)): return "N/A"
    v = float(v)
    if abs(v) >= 1e9: return f"{v / 1e9:.2f}B"
    if abs(v) >= 1e6: return f"{v / 1e6:.2f}M"
    if abs(v) >= 1e3: return f"{v / 1e3:.1f}K"
    return f"{v:,.0f}"

def cls(v): return "red" if (v or 0) > 0 else ("green" if (v or 0) < 0 else "")  # 한국식: 상승=빨강, 하락=초록(파랑)

def h(*parts): return "".join(p for p in parts if p)

DISCLAIMER = ('<div class="disc">⚠️ 본 대시보드는 개인 연구용이며 <b>투자 권유·투자 자문이 아닙니다</b>. '
              '진입가·잔존 숏·재점화 레벨·확률·매수구간은 모두 <b>무료 공개 데이터 기반 추정치</b>이며 실제와 다를 수 있습니다. '
              '무료 데이터는 지연(약 1~15분)될 수 있습니다. 모든 투자 판단과 손실 책임은 본인에게 있습니다.</div>')


def skeleton(lines=4, title=None):
    w = [38, 70, 92, 60, 80, 50]
    t = f'<div class="muted" style="margin-bottom:4px">{title}</div>' if title else ""
    return '<div class="skel">' + t + "".join(f'<div class="ln" style="width:{w[i % len(w)]}%"></div>' for i in range(lines)) + '</div>'
