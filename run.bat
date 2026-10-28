@echo off
chcp 65001 >nul
title 공매도 대시보드
cd /d "%~dp0"
set "PY=python"
where py >nul 2>nul && set "PY=py -3"
%PY% --version >nul 2>nul || (
  echo [오류] Python 이 설치되어 있지 않습니다. https://www.python.org/downloads/ 에서 설치하세요.
  echo        설치 화면에서 "Add python.exe to PATH" 를 꼭 체크하세요.
  pause & exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  echo [1/3] 가상환경 만드는 중... ^(처음 한 번만^)
  %PY% -m venv .venv || (pause & exit /b 1)
)
if not exist ".venv\.installed" (
  echo [2/3] 필요한 패키지 설치 중... ^(처음 한 번만, 몇 분 걸림^)
  ".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt || (pause & exit /b 1)
  echo ok> ".venv\.installed"
)
echo [3/3] 대시보드 실행
echo.
echo  PC 에서:   http://localhost:8501
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4"') do (
  for /f "tokens=* delims= " %%b in ("%%a") do echo  폰에서:   http://%%b:8501   ^(같은 Wi-Fi^)
)
echo.
echo  이 창을 닫으면 대시보드가 꺼집니다.
".venv\Scripts\python.exe" -m streamlit run app.py --server.address 0.0.0.0 --server.port 8501 --browser.gatherUsageStats false
pause
