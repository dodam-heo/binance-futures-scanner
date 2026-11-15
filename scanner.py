#!/usr/bin/env python3
"""Public Binance USD-M perpetual market snapshot. No credentials or trades."""
import json, os, time, math, statistics, urllib.request, urllib.error
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

BASES=["https://fapi.binance.com","https://fapi1.binance.com","https://fapi2.binance.com","https://fapi3.binance.com","https://fapi4.binance.com","https://api-dev.pipai.org"]
ACTIVE_BASE=None
DIAGNOSTICS=[]
def get(path):
    global ACTIVE_BASE
    errors=[]
    bases=([ACTIVE_BASE] if ACTIVE_BASE else [])+[b for b in BASES if b!=ACTIVE_BASE]
    for base in bases:
        try:
            req=urllib.request.Request(base+path,headers={"User-Agent":"market-data-research/1.0","Accept":"application/json"})
            with urllib.request.urlopen(req,timeout=12) as r:
                raw=r.read()
                try: data=json.loads(raw)
                except ValueError: raise ValueError("non-JSON HTTP %s body=%r"%(r.status,raw[:160]))
                if isinstance(data,dict) and ("code" in data and "msg" in data):raise ValueError("API error "+str(data)[:200])
                ACTIVE_BASE=base
                return data
        except Exception as e:
            err=base+" "+path.split("?")[0]+": "+str(e)[:200]
            errors.append(err)
            if len(DIAGNOSTICS)<40:DIAGNOSTICS.append(err)
    raise RuntimeError("; ".join(errors))
def atr(rows,period=14):
    if len(rows)<period+1:return None
    tr=[]
    for i in range(1,len(rows)):
        h,l,prev=float(rows[i][2]),float(rows[i][3]),float(rows[i-1][4])
        tr.append(max(h-l,abs(h-prev),abs(l-prev)))
    return sum(tr[-period:])/period
def candles(sym):
    from urllib.parse import quote
    q=quote(sym)
    h1=get("/fapi/v1/klines?symbol="+q+"&interval=1h&limit=120")
    h4=get("/fapi/v1/klines?symbol="+q+"&interval=4h&limit=120")
    # Exclude open candle for stable indicators.
    now=int(time.time()*1000)
    h1=[x for x in h1 if int(x[6])<now]
    h4=[x for x in h4 if int(x[6])<now]
    def calc(rows):
        closes=[float(x[4]) for x in rows]
        highs=[float(x[2]) for x in rows[-20:]]
        lows=[float(x[3]) for x in rows[-20:]]
        return {"atr14":atr(rows),"high20":max(highs),"low20":min(lows),
                "sma20":sum(closes[-20:])/20,"sma50":sum(closes[-50:])/50,
                "last_close":closes[-1],"last_close_ms":int(rows[-1][6]),
                "last_volume":float(rows[-1][7]),
                "avg_volume20":sum(float(x[7]) for x in rows[-20:])/20}
    return sym,{"h1":calc(h1),"h4":calc(h4)}
def main():
    os.makedirs("data",exist_ok=True)
    out={"timestamp_utc":datetime.now(timezone.utc).isoformat(),"source":"Binance USD-M Futures REST API or PipAI mirror","status":"error","error":None,"universe_count":0,"deep_count":0,"incomplete":True,"symbols":[],"deep":{}}
    try:
        exchange=get("/fapi/v1/exchangeInfo")
        universe={s["symbol"] for s in exchange["symbols"] if s.get("status")=="TRADING" and s.get("contractType")=="PERPETUAL" and s.get("quoteAsset")=="USDT"}
        out["universe_count"]=len(universe)
        tick=get("/fapi/v1/ticker/24hr")
        rows=[]
        for t in tick:
            if t["symbol"] not in universe:continue
            rows.append({"symbol":t["symbol"],"last":float(t["lastPrice"]),"high24":float(t["highPrice"]),"low24":float(t["lowPrice"]),"change24_pct":float(t["priceChangePercent"]),"quote_volume24":float(t["quoteVolume"])})
        out["symbols"]=rows
        if len(rows)!=len(universe):raise RuntimeError("24h ticker incomplete: %s/%s"%(len(rows),len(universe)))
        liquid=[x for x in rows if x["quote_volume24"]>=10000000 and x["last"]>0]
        liquid.sort(key=lambda x:x["quote_volume24"]*max(abs(x["change24_pct"]),1),reverse=True)
        chosen=liquid[:30]
        deep={}
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures={pool.submit(candles,x["symbol"]):x["symbol"] for x in chosen}
            for f in as_completed(futures):
                try:
                    sym,data=f.result()
                    deep[sym]=data
                except Exception as e:
                    deep[futures[f]]={"error":str(e)[:350]}
        out["deep"]=deep
        out["active_base"]=ACTIVE_BASE
        out["deep_count"]=sum("error" not in x for x in deep.values())
        out["incomplete"]=out["deep_count"]<20
        out["status"]="ok" if not out["incomplete"] else "partial"
    except Exception as e:out["error"]=str(e)[:1600]
    out["timestamp_utc"]=datetime.now(timezone.utc).isoformat()
    out["diagnostics"]=DIAGNOSTICS
    out["active_base"]=ACTIVE_BASE
    with open("data/latest.json","w") as f:json.dump(out,f,ensure_ascii=False,separators=(",",":"),allow_nan=False)
    print(json.dumps({k:out[k] for k in ["timestamp_utc","status","universe_count","deep_count","incomplete","error"]},ensure_ascii=False))
    if out["status"]!="ok":raise SystemExit(1)
if __name__=="__main__":main()
