#!/usr/bin/env python3
"""Conservative chronological paper fills. No real orders or trade signals."""
import json, os
from datetime import datetime, timezone, timedelta
from urllib.parse import quote
from scanner import get

PATH="data/paper_ledger.json"
def simulate(trade, bars, cost_pct=None):
    """Bars must be chronological CLOSED candles [open_ms, open, high, low, close].
    Entry is valid only after setup timestamp. In ambiguous OHLC bars, stop wins.
    """
    side=trade["direction"]; entry=float(trade["entry"])
    tp=float(trade["take_profit"]); stop=float(trade["stop_loss"])
    if side not in ("LONG","SHORT"):raise ValueError("bad side")
    if not (stop<entry<tp if side=="LONG" else tp<entry<stop):
        raise ValueError("invalid price geometry")
    start=int(trade["created_ms"]); deadline=int(trade["expires_ms"])
    cost=float(cost_pct if cost_pct is not None else trade["cost_notional_pct"])
    entered=False; entry_ms=None
    for bar in sorted(bars,key=lambda x:int(x[0])):
        ts=int(bar[0]); hi=float(bar[2]); lo=float(bar[3])
        if ts<start or ts>=deadline:continue
        if hi<lo:raise ValueError("bad candle")
        if not entered:
            if not(lo<=entry<=hi):continue
            entered=True;entry_ms=ts
            # Same candle TP cannot be verified to occur AFTER limit entry.
            # Stop is conservatively assumed to occur after entry if touched.
            if (lo<=stop if side=="LONG" else hi>=stop):
                return {"status":"STOP","entry_ms":entry_ms,"exit_ms":ts,
                        "net_margin_pct":round(300*((stop-entry)/entry if side=="LONG" else (entry-stop)/entry)-3*cost,3),
                        "ambiguity":"entry-and-stop-same-bar"}
            continue
        hit_stop=(lo<=stop if side=="LONG" else hi>=stop)
        hit_tp=(hi>=tp if side=="LONG" else lo<=tp)
        if hit_stop or hit_tp:
            result="STOP" if hit_stop else "TP"
            exit_price=stop if hit_stop else tp
            gross=((exit_price-entry)/entry if side=="LONG" else (entry-exit_price)/entry)
            return {"status":result,"entry_ms":entry_ms,"exit_ms":ts,
                    "net_margin_pct":round(300*gross-3*cost,3),
                    "ambiguity":"both-hit-stop-first" if hit_stop and hit_tp else None}
    return {"status":"OPEN" if entered else "UNFILLED","entry_ms":entry_ms,
            "exit_ms":None,"net_margin_pct":None,"ambiguity":None}

def main():
    os.makedirs("data",exist_ok=True)
    ledger={"version":1,"trades":[]}
    if os.path.exists(PATH):
        with open(PATH) as f:ledger=json.load(f)
    with open("data/latest.json") as f:snapshot=json.load(f)
    now=datetime.now(timezone.utc)
    now_ms=int(now.timestamp()*1000)
    existing={t["id"] for t in ledger["trades"]}
    # A new paper setup is recorded only when scan is complete and fresh.
    scan_time=datetime.fromisoformat(snapshot["timestamp_utc"])
    fresh=(now-scan_time).total_seconds()<900
    if snapshot.get("status")=="ok" and fresh:
        for c in snapshot.get("research_candidates",[])[:10]:
            created=int(scan_time.timestamp()*1000)
            kst=scan_time+timedelta(hours=9)
            midnight=kst.replace(hour=23,minute=59,second=0,microsecond=0)-timedelta(hours=9)
            t=dict(c)
            t.update({"id":str(created)+":"+c["symbol"]+":"+c["direction"],
                      "created_ms":created,"expires_ms":int(midnight.timestamp()*1000),
                      "status":"PENDING","paper_only":True})
            if t["id"] not in existing:
                ledger["trades"].append(t);existing.add(t["id"])
    # Limit tracking to recent setups and avoid an unbounded API load.
    pending=[t for t in ledger["trades"] if t["status"] in ("PENDING","OPEN") and
             now_ms-int(t["created_ms"])<3*86400000]
    for t in pending:
        try:
            raw=get("/fapi/v1/klines?symbol="+quote(t["symbol"])+"&interval=1h&limit=72")
            bars=[[int(b[0]),float(b[1]),float(b[2]),float(b[3]),float(b[4])]
                  for b in raw if int(b[6])<now_ms]
            result=simulate(t,bars)
            if result["status"] in ("TP","STOP"):
                t.update(result)
            elif now_ms>=int(t["expires_ms"]):
                # At expiry, mark unresolved, not a profitable trade.
                t.update({"status":"EXPIRED_"+result["status"],
                          "entry_ms":result["entry_ms"],"exit_ms":None,
                          "net_margin_pct":None})
            else:
                t["status"]="OPEN" if result["status"]=="OPEN" else "PENDING"
                t["entry_ms"]=result["entry_ms"]
        except Exception as e:t["tracking_error"]=str(e)[:200]
    ledger["updated_utc"]=now.isoformat()
    ledger["trades"]=ledger["trades"][-2000:]
    counts={}
    for t in ledger["trades"]:counts[t["status"]]=counts.get(t["status"],0)+1
    ledger["counts"]=counts
    ledger["validation_status"]="PAPER_ONLY_NOT_BACKTESTED"
    with open(PATH,"w") as f:json.dump(ledger,f,separators=(",",":"),allow_nan=False)
    print(json.dumps({"paper_counts":counts,"tracking_errors":sum(bool(t.get("tracking_error")) for t in pending)}))

if __name__=="__main__":main()
