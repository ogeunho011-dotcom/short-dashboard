"""85개 성공/실패 사례에 대해 시점 기준(point-in-time) SHFS 스타일 카드·서사·이벤트 로그 생성 → model/case_cards.json"""
import sys, json, traceback
sys.path.insert(0, '.')
import pandas as pd
from core import model, params as P
p = P.load()
cases = pd.read_pickle('data/sa_cases.pkl')
out = []
def ser(v):
    if isinstance(v, (pd.Timestamp,)): return str(v.date())
    if hasattr(v, 'item'): return v.item()
    return v
for r in cases.itertuples(index=False):
    d = r._asdict()
    try:
        x = model.hist_case(d['ticker'], str(pd.Timestamp(d['date']).date()), p)
    except Exception as e:
        print('ERR', d['ticker'], d['date'], e); traceback.print_exc(limit=1); continue
    if not x: print('skip', d['ticker'], d['date']); continue
    bz, f = x.get('bz') or {}, x['f']
    tr = [{k: ser(v) for k, v in t.items() if not isinstance(v, (list, dict, pd.DataFrame))} for t in x['meta'].get('tranches', [])]
    out.append(dict(key=d.get('key'), ticker=d['ticker'], date=str(pd.Timestamp(d['date']).date()), group=d.get('group'),
        cat=d.get('cat'), cause=d.get('cause'), link=d.get('link'),
        narr=x['narr'], events=[[str(pd.Timestamp(a).date()), b] for a, b in x['events']],
        post=[[str(pd.Timestamp(a).date()), b] for a, b in x['post']], result=x['result'],
        price=ser(f.get('price')), rl=ser(x['meta'].get('reignite')), ph=ser(x.get('ph')), stop=ser(bz.get('stop')),
        cp=ser(f.get('cover_pressure')), level=ser(x['s'].get('level')), loss_pct=ser(f.get('loss_side')), tranches=tr))
json.dump(out, open('model/case_cards.json', 'w'), ensure_ascii=False, indent=1, default=str)
print('saved', len(out))
