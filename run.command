#!/bin/bash
# 공매도 대시보드 — Mac 원클릭 실행 (더블클릭)
cd "$(dirname "$0")" || exit 1
PY=$(command -v python3 || true)
if [ -z "$PY" ]; then
  echo "[오류] python3 가 없습니다. https://www.python.org/downloads/ 에서 설치하세요."; read -r -p "엔터를 누르면 닫힙니다"; exit 1
fi
if [ ! -x .venv/bin/python ]; then
  echo "[1/3] 가상환경 만드는 중... (처음 한 번만)"; "$PY" -m venv .venv || exit 1
fi
if [ ! -f .venv/.installed ]; then
  echo "[2/3] 필요한 패키지 설치 중... (처음 한 번만, 몇 분 걸림)"
  .venv/bin/python -m pip install --upgrade pip >/dev/null
  .venv/bin/python -m pip install -r requirements.txt || { read -r -p "설치 실패. 엔터를 누르면 닫힙니다"; exit 1; }
  touch .venv/.installed
fi
IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}')
echo "[3/3] 대시보드 실행"
echo
echo "  PC 에서:   http://localhost:8501"
[ -n "$IP" ] && echo "  폰에서:   http://$IP:8501   (같은 Wi-Fi)"
echo
echo "  이 창을 닫으면 대시보드가 꺼집니다."
exec .venv/bin/python -m streamlit run app.py --server.address 0.0.0.0 --server.port 8501 --browser.gatherUsageStats false
