#!/usr/bin/env python3
"""Public Binance USD-M perpetual market snapshot. No credentials or trades."""
import json, os, time, math, statistics, gzip, urllib.request, urllib.error
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
                if raw[:2]==b'\x1f\x8b': raw=gzip.decompress(raw)
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
                "avg_volume20":sum(float(x[7]) for x in rows[-20:])/20,
                "recent_high5":max(float(x[2]) for x in rows[-5:]),
                "recent_low5":min(float(x[3]) for x in rows[-5:]),
                "prev_high20":max(float(x[2]) for x in rows[-21:-1]),
                "prev_low20":min(float(x[3]) for x in rows[-21:-1])}
    return sym,{"h1":calc(h1),"h4":calc(h4)}

def verify_trade(sym, data, tick, remaining_hours):
    """Conservative structural setups, never guaranteed executable trades."""
    from urllib.parse import quote
    h=data["h1"]; h4=data["h4"]; p=float(tick["last"]); a=h["atr14"]
    if not a or p<=0 or remaining_hours<2 or tick["quote_volume24"]<20000000:return []
    if h["last_volume"]<h["avg_volume20"] or abs(p-h["last_close"])>0.35*a:return []
    long_ok=(h4["last_close"]>h4["sma20"]>h4["sma50"] and h["last_close"]>h["sma20"]>h["sma50"])
    short_ok=(h4["last_close"]<h4["sma20"]<h4["sma50"] and h["last_close"]<h["sma20"]<h["sma50"])
    if not(long_ok or short_ok):return []
    q=quote(sym)
    premium=get("/fapi/v1/premiumIndex?symbol="+q)
    book=get("/fapi/v1/depth?symbol="+q+"&limit=20")
    bids=[(float(v),float(n)) for v,n in book.get("bids",[])]
    asks=[(float(v),float(n)) for v,n in book.get("asks",[])]
    if not bids or not asks:raise ValueError("empty orderbook")
    mid=(bids[0][0]+asks[0][0])/2
    spread=(asks[0][0]-bids[0][0])/mid
    if spread>0.0008:return []
    def impact(levels):
        left=1000.;qty=0.
        for price,amount in levels:
            value=min(left,price*amount)
            qty+=value/price;left-=value
            if left<=0:break
        if left>0:raise ValueError("insufficient depth")
        return 1000./qty
    slip=max(impact(asks)/mid-1,1-impact(bids)/mid,0)
    if slip>0.0008:return []
    funding=abs(float(premium.get("lastFundingRate",0)))
    cost=0.001+2*max(slip,0.00025)+0.0001+funding
    result=[]
    for side,ok in (("LONG",long_ok),("SHORT",short_ok)):
        if not ok:continue
        # Only consider a nearby SMA20 retest; don't assume that it will fill.
        entry=h["sma20"]
        if abs(entry-p)>0.25*a:continue
        # Structural invalidation uses the preceding five completed bars.
        stop=(h["recent_low5"]-0.1*a if side=="LONG" else h["recent_high5"]+0.1*a)
        # Prior swing extremum is a *candidate* exit, not a predicted destination.
        target=(h["prev_high20"] if side=="LONG" else h["prev_low20"])
        risk=(entry-stop if side=="LONG" else stop-entry)
        reward=(target-entry if side=="LONG" else entry-target)
        if risk<=0 or reward<=0:continue
        if risk>1.2*a or reward>1.0*a:continue
        # Require enough movement after a hypothetical entry; ATR is a cap,
        # not an entry-before-exit probability model.
        if abs(entry-p)+reward>min(1.5*a,a*math.sqrt(remaining_hours)):continue
        net=3*(reward/entry-cost)
        loss=3*(risk/entry+cost)
        if net<0.05 or loss<=0 or net/loss<1.5:continue
        result.append({"symbol":sym,"direction":side,"snapshot_price":p,
            "entry":entry,"take_profit":target,"stop_loss":stop,
            "net_margin_pct":round(net*100,2),
            "stop_margin_loss_pct":round(loss*100,2),
            "reward_risk":round(net/loss,2),
            "funding_rate":funding,"spread_pct":round(spread*100,4),
            "book_slippage_pct":round(slip*100,4),"atr1h":a,
            "cost_notional_pct":round(cost*100,4),
            "entry_basis":"1h SMA20 retest, conditional",
            "stop_basis":"last five closed 1h candles plus 0.1 ATR buffer",
            "target_basis":"previous 20 closed 1h candles swing extreme",
            "validation":"UNVERIFIED - paper testing and chronological fill validation required",
            "note":"NOT AN ORDER: historical extrema and ATR cannot establish intraday fill probability"})
    return result

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
        liquid=[x for x in rows if x["last"]>0]
        liquid.sort(key=lambda x:x["quote_volume24"]*max(abs(x["change24_pct"]),1),reverse=True)
        chosen=liquid
        deep={}
        with ThreadPoolExecutor(max_workers=12) as pool:
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
        kst=datetime.now(timezone.utc).timestamp()+9*3600
        remaining_hours=max(0,((int(kst//86400)+1)*86400-60-kst)/3600)
        verified=[];verification_errors={}
        for sym,ind in deep.items():
            if "error" in ind:continue
            if next(x for x in rows if x["symbol"]==sym)["quote_volume24"]<10000000:continue
            try:
                tickrow=next(x for x in rows if x["symbol"]==sym)
                verified.extend(verify_trade(sym,ind,tickrow,remaining_hours))
            except Exception as e:verification_errors[sym]=str(e)[:240]
        verified.sort(key=lambda x:(x["reward_risk"],x["net_margin_pct"]),reverse=True)
        out["research_candidates"]=verified[:10] if not (out["deep_count"]<len(chosen) or verification_errors) else []
        out["trade_screen"]=[]  # Disable actionable signals until chronological paper validation
        out["trade_screen_count"]=0
        out["research_candidate_count"]=len(verified)
        out["signal_status"]="DISABLED_PENDING_PAPER_VALIDATION"
        out["verification_errors"]=verification_errors
        out["remaining_hours_kst"]=round(remaining_hours,3)
        out["trade_screen_disclaimer"]="No actionable orders until independent forward validation of entry-before-exit sequence and net realized returns."
        out["missing_symbols"]=[sym for sym,item in deep.items() if "error" in item]
        out["incomplete"]=out["deep_count"]<len(chosen) or bool(verification_errors)
        out["status"]="ok" if not out["incomplete"] else "partial"
    except Exception as e:out["error"]=str(e)[:1600]
    out["timestamp_utc"]=datetime.now(timezone.utc).isoformat()
    out["diagnostics"]=DIAGNOSTICS
    out["active_base"]=ACTIVE_BASE
    with open("data/latest.json","w") as f:json.dump(out,f,ensure_ascii=False,separators=(",",":"),allow_nan=False)
    print(json.dumps({k:out[k] for k in ["timestamp_utc","status","universe_count","deep_count","incomplete","error"]},ensure_ascii=False))
    if out["status"]!="ok":raise SystemExit(1)
if __name__=="__main__":main()
