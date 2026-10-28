"""OOS 경보 → 이벤트 묶기(같은 종목 7일 이내). 입력 data/sa_alerts.pkl (scripts/sa_lib 로 생성), 출력 data/sa_events.pkl"""
import pandas as pd, numpy as np, sqlite3
A=pd.read_pickle("data/sa_alerts.pkl").sort_values(["ticker","asof"])
c=sqlite3.connect("data/shortdash.sqlite")
px=pd.read_sql("select ticker,date,open,high,low,close,volume from prices",c); px["date"]=pd.to_datetime(px.date)
D={t:g.reset_index(drop=True) for t,g in px.groupby("ticker")}
def fdate(t,d,k):
    g=D[t]; i=g.index[g.date==d]
    return g.date.iloc[i[0]+k] if len(i) and i[0]+k<len(g) else pd.NaT
A["peak_date"]=[fdate(t,d,k) for t,d,k in zip(A.ticker,A["asof"],A.upday)]
# event clustering: same ticker, alerts within 7 calendar days of previous alert -> same event
ev=[];last={}
for i,r in A.iterrows():
    t=r.ticker
    if t in last and (r["asof"]-last[t][1]).days<=7: eid=last[t][0]
    else: eid=len(set(e for e in ev))
    ev.append(eid); last[t]=(eid,r["asof"])
A["event"]=ev
E=A.groupby("event").agg(ticker=("ticker","first"),first=("asof","min"),last=("asof","max"),n_alerts=("hit","size"),any_hit=("hit","max"),first_hit=("hit","first"),
    maxup=("maxup","max"),minlo=("minlo","min"),price=("price","first"))
print(len(E), E.first_hit.mean(), E.any_hit.mean()); print(E.n_alerts.describe())
A.to_pickle("data/sa_alerts.pkl"); E.to_pickle("data/sa_events.pkl")
