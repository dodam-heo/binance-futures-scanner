#!/usr/bin/env python3
"""Offline walk-forward replay from locally supplied historical Binance kline JSON.
No future candles are used in setup generation. No real orders.
Usage: python backtest.py --h1 history/ETHUSDT-1h.json --h4 history/ETHUSDT-4h.json --symbol ETHUSDT
"""
import argparse, json, math
from datetime import datetime, timezone, timedelta
from paper_validate import simulate

def stats(rows):
    if len(rows)<51:return None
    closes=[float(x[4]) for x in rows]
    trs=[]
    for i in range(1,len(rows)):
        hi,lo,prev=float(rows[i][2]),float(rows[i][3]),float(rows[i-1][4])
        trs.append(max(hi-lo,abs(hi-prev),abs(lo-prev)))
    return {"sma20":sum(closes[-20:])/20,"sma50":sum(closes[-50:])/50,
            "last_close":closes[-1],"atr":sum(trs[-14:])/14,
            "volume":float(rows[-1][7]),
            "avg_volume":sum(float(x[7]) for x in rows[-20:])/20,
            "low5":min(float(x[3]) for x in rows[-5:]),
            "high5":max(float(x[2]) for x in rows[-5:]),
            "prev_low20":min(float(x[3]) for x in rows[-21:-1]),
            "prev_high20":max(float(x[2]) for x in rows[-21:-1])}

def replay(h1,h4,symbol,cost_pct=0.25):
    h1=sorted(h1,key=lambda b:int(b[0]));h4=sorted(h4,key=lambda b:int(b[0]))
    trades=[]
    last_setup_expiry=0
    # Timestamp in Binance kline column 6 is close time; only use fully closed candles.
    for i in range(51,len(h1)-1):
        last=int(h1[i][6]);now=last+1
        if now<last_setup_expiry:continue
        history4=[x for x in h4 if int(x[6])<=last]
        if len(history4)<51:continue
        a=stats(h1[:i+1]);b=stats(history4)
        if a["atr"]<=0 or a["volume"]<a["avg_volume"]:continue
        long_ok=(a["last_close"]>a["sma20"]>a["sma50"] and b["last_close"]>b["sma20"]>b["sma50"])
        short_ok=(a["last_close"]<a["sma20"]<a["sma50"] and b["last_close"]<b["sma20"]<b["sma50"])
        if not(long_ok or short_ok):continue
        # 1h close as observable reference; SMA20 retest is a future limit order.
        p=a["last_close"];entry=a["sma20"]
        if abs(entry-p)>0.25*a["atr"]:continue
        kst=datetime.fromtimestamp(now/1000,timezone.utc)+timedelta(hours=9)
        deadline=(kst.replace(hour=23,minute=59,second=0,microsecond=0)-timedelta(hours=9))
        end=int(deadline.timestamp()*1000)
        if end-now<2*3600000:continue
        for side,valid in (("LONG",long_ok),("SHORT",short_ok)):
            if not valid:continue
            stop=(a["low5"]-0.1*a["atr"] if side=="LONG" else a["high5"]+0.1*a["atr"])
            tp=(a["prev_high20"] if side=="LONG" else a["prev_low20"])
            risk=(entry-stop if side=="LONG" else stop-entry)
            reward=(tp-entry if side=="LONG" else entry-tp)
            if risk<=0 or reward<=0 or risk>1.2*a["atr"] or reward>a["atr"]:continue
            net=3*(reward/entry-cost_pct/100)
            loss=3*(risk/entry+cost_pct/100)
            if net<0.05 or net/loss<1.5:continue
            setup={"symbol":symbol,"direction":side,"entry":entry,"stop_loss":stop,
                   "take_profit":tp,"created_ms":now,"expires_ms":end,
                   "cost_notional_pct":cost_pct}
            future=[[int(x[0]),float(x[1]),float(x[2]),float(x[3]),float(x[4])]
                    for x in h1[i+1:] if int(x[6])<end]
            result=simulate(setup,future)
            if result["status"] in ("OPEN","UNFILLED"):
                result["status"]="EXPIRED_"+result["status"]
            trades.append({"setup_ms":now,"symbol":symbol,"side":side,**result})
            last_setup_expiry=end
            break
    closed=[x for x in trades if x["status"] in ("TP","STOP")]
    filled=[x for x in trades if x["status"] not in ("EXPIRED_UNFILLED","UNFILLED")]
    pnl=[x["net_margin_pct"] for x in closed]
    return {"symbol":symbol,"setups":len(trades),"filled":len(filled),
            "closed":len(closed),"take_profits":sum(x["status"]=="TP" for x in closed),
            "stops":sum(x["status"]=="STOP" for x in closed),
            "unfilled":sum(x["status"]=="EXPIRED_UNFILLED" for x in trades),
            "expired_open":sum(x["status"]=="EXPIRED_OPEN" for x in trades),
            "entry_fill_rate":len(filled)/len(trades) if trades else None,
            "closed_win_rate":sum(x["status"]=="TP" for x in closed)/len(closed) if closed else None,
            "mean_closed_margin_pct":sum(pnl)/len(pnl) if pnl else None,
            "trades":trades}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--h1",required=True);p.add_argument("--h4",required=True)
    p.add_argument("--symbol",required=True);p.add_argument("--cost-pct",type=float,default=0.25)
    p.add_argument("--output",default="data/backtest_result.json")
    args=p.parse_args()
    with open(args.h1) as f:h1=json.load(f)
    with open(args.h4) as f:h4=json.load(f)
    report=replay(h1,h4,args.symbol,args.cost_pct)
    import os
    os.makedirs(os.path.dirname(args.output) or ".",exist_ok=True)
    with open(args.output,"w") as f:json.dump(report,f,indent=2)
    print(json.dumps({k:v for k,v in report.items() if k!="trades"},indent=2))
if __name__=="__main__":main()
