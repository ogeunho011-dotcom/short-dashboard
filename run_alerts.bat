@echo off
chcp 65001 >nul
title 숏 레이더 알림 스캐너
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo [안내] 먼저 run.bat 을 한 번 실행해 설치를 끝내 주세요.
  pause & exit /b 1
)
echo 급등 신호 알림 스캐너 — 미국 프리마켓~애프터마켓 동안 10분마다 확인합니다.
echo (클라우드 GitHub Actions 알림을 쓰면 이 창은 필요 없습니다.)
echo 이 창을 닫으면 알림이 멈춥니다.
echo.
".venv\Scripts\python.exe" scripts\alerts_run.py --loop 10
pause
