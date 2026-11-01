"""Fetch 1m OHLCV for every liq>=50k candidate pool (cache research/meme_paths.json)."""
import json, time, requests, datetime as dt, os
R=[json.loads(l) for l in open('candidates_solana.jsonl')]
pools={}
for r in R:
    if (r.get('liq') or 0)>=50000 and r.get('pair'): pools[r['pair']]=r['mint']
P=json.load(open('research/meme_paths.json')) if os.path.exists('research/meme_paths.json') else {}
for pair in pools:
    if pair in P and time.time()-P[pair]['at']<1800: continue
    time.sleep(2.2)
    try:
        d=requests.get(f"https://api.geckoterminal.com/api/v2/networks/solana/pools/{pair}/ohlcv/minute",params=dict(aggregate=1,limit=1000,currency='usd'),timeout=15).json()
        P[pair]={'at':time.time(),'bars':sorted(x[:6] for x in d['data']['attributes']['ohlcv_list'])}
    except Exception as e: print(pair,e)
json.dump(P,open('research/meme_paths.json','w')); print(len(P))
