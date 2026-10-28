"""(구버전 호환) 장중 재스캔 + 알림 → scripts/alerts_run.py 로 통합되었습니다.
python scripts/rescan_intraday.py --loop 10  ==  python scripts/alerts_run.py --loop 10"""
import sys, os, runpy
sys.argv[0] = os.path.join(os.path.dirname(os.path.abspath(__file__)), "alerts_run.py")
runpy.run_path(sys.argv[0], run_name="__main__")
