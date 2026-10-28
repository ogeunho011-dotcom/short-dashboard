#!/bin/bash
# 숏 레이더 알림 스캐너 — Mac (더블클릭). 먼저 run.command 로 설치를 끝내 주세요.
cd "$(dirname "$0")" || exit 1
[ -x .venv/bin/python ] || { echo "먼저 run.command 를 한 번 실행하세요."; read -r -p "엔터"; exit 1; }
echo "급등 신호 알림 스캐너 — 미국 프리마켓~애프터마켓 동안 10분마다 확인합니다. 창을 닫으면 멈춥니다."
exec .venv/bin/python scripts/alerts_run.py --loop 10
