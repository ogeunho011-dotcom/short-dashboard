"""playwright 헤드리스로 모바일 폭(390px) 스크린샷 저장. streamlit 이 8501 에서 실행 중이어야 함."""
import sys, os, time
from playwright.sync_api import sync_playwright
BASE = os.environ.get("APP_URL", "http://localhost:8501")
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "screenshots")
PAGES = [a.split("=", 1) for a in sys.argv[1:]] or [["01_home", "?p=home"], ["02_stock_SOUN", "?p=stock&t=SOUN"], ["03_stock_TDIC", "?p=stock&t=TDIC"],
          ["04_live", "?p=live"], ["05_track", "?p=track"], ["06_admin", "?p=admin"]]
os.makedirs(OUT, exist_ok=True)
with sync_playwright() as pw:
    br = pw.chromium.launch(executable_path="/usr/bin/google-chrome", headless=True, args=["--no-sandbox"])
    ctx = br.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True)
    for name, q in PAGES:
        pg = ctx.new_page()
        pg.goto(BASE + "/" + q, wait_until="networkidle", timeout=180000)
        try:
            pg.wait_for_selector(".nav", timeout=180000)
            pg.wait_for_function("() => !document.querySelector('[data-testid=\"stStatusWidget\"]') || !document.querySelector('[data-testid=\"stStatusWidget\"]').innerText.includes('Running')", timeout=180000)
        except Exception as e:
            print("wait fail", name, e)
        time.sleep(3)
        hgt = pg.evaluate("() => { const m = document.querySelector('[data-testid=\"stMain\"]') || document.querySelector('section.main'); return Math.max(m ? m.scrollHeight : 0, document.body.scrollHeight); }")
        pg.set_viewport_size({"width": 390, "height": min(int(hgt) + 40, 16000)}); time.sleep(1.5)
        pg.screenshot(path=f"{OUT}/{name}.png", full_page=True)
        ex = pg.query_selector_all('[data-testid="stException"]')
        print("saved", name, "예외", len(ex), (ex[0].inner_text()[:300] if ex else ""))
        # 상세 페이지는 캐러셀 카드별로 추가 캡처
        if name.startswith("02_stock"):
            for i in range(1, 4):
                pg.evaluate(f"() => {{ const c = document.querySelector('.carousel'); if (c) c.scrollLeft = c.children[{i}].offsetLeft - 10; }}")
                time.sleep(0.8)
                el = pg.query_selector(".carousel")
                if el: el.screenshot(path=f"{OUT}/{name}_card{i + 1}.png")
            el = pg.query_selector(".carousel")
            pg.evaluate("() => { const c = document.querySelector('.carousel'); if (c) c.scrollLeft = 0; }"); time.sleep(0.5)
            if el: el.screenshot(path=f"{OUT}/{name}_card1.png")
        pg.close()
    br.close()
