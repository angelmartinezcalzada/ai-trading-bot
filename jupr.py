import os
"""central Jupiter rate limiter: token bucket + priority (0 exit > 1 buy > 2 pricing), 429 backoff with jitter, short quote cache, stats."""
import threading, time, random, json, contextlib, requests
RATE, CAP = 0.5, 3.0                 # tokens/s sustained, burst
RESERVE = {0: 0.0, 1: 0.5, 2: 1.0}   # tokens that must remain after taking one (lower prio waits)
_lk = threading.Lock(); _tok = CAP; _t = time.time(); _cool = 0.0
_loc = threading.local(); _cache = {}
STATS = {"calls": 0, "r429": 0, "cache_hits": 0, "since": time.time()}
@contextlib.contextmanager
def prio(p):
    old = getattr(_loc, "p", None); _loc.p = p
    try: yield
    finally: _loc.p = old
def _take(p, timeout=60):
    global _tok, _t
    t0 = time.time()
    while True:
        with _lk:
            now = time.time(); _tok = min(CAP, _tok + (now-_t)*RATE); _t = now
            if now >= _cool or p == 0:
                if _tok - 1 >= -0.0001 + RESERVE[p] - (0 if p else RESERVE[p]):
                    _tok -= 1; return True
        if time.time()-t0 > timeout: return False
        time.sleep(0.05 + 0.1*p + random.random()*0.05)
def _dump():
    if STATS["calls"] % 20 == 0:
        try: json.dump(STATS, open("jup_stats.json", "w"))
        except Exception: pass
def request(method, url, prio_=None, cache_s=0, **kw):
    global _cool
    p = prio_ if prio_ is not None else (getattr(_loc, "p", None) if getattr(_loc, "p", None) is not None else 2)
    key = None
    if method == "GET" and cache_s and p == 2:
        key = (url, json.dumps(kw.get("params") or {}, sort_keys=True)); c = _cache.get(key)
        if c and time.time()-c[0] < cache_s: STATS["cache_hits"] += 1; return c[1]
    for i in range(4):
        if not _take(p): raise RuntimeError("jupiter limiter timeout")
        STATS["calls"] += 1; _dump()
        u, kw2 = url, dict(kw)
        if os.environ.get("JUP_API_KEY") and "lite-api.jup.ag" in url:   # optional paid/free key: api.jup.ag + x-api-key; absent -> lite-api
            u = url.replace("lite-api.jup.ag", "api.jup.ag"); kw2["headers"] = {**(kw2.get("headers") or {}), "x-api-key": os.environ["JUP_API_KEY"]}
        r = requests.request(method, u, timeout=kw2.pop("timeout", 15), **kw2)
        if r.status_code == 429:
            STATS["r429"] += 1
            with _lk: _cool = max(_cool, time.time() + (1.5*2**i)*(0.7+0.6*random.random()))
            time.sleep((0.5 if p == 0 else 1.5)*2**i*(0.7+0.6*random.random())); continue
        if key and r.ok: _cache[key] = (time.time(), r)
        if len(_cache) > 2000: _cache.clear()
        return r
    return r
