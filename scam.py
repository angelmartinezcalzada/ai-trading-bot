"""Solana scam / rug filter. check(mint, sym, price, cfg) -> list of flags (empty = clean). Every check is independent and logged."""
import json, os, re, time, requests
H = {"User-Agent": "Mozilla/5.0"}; _c = {}; BL = "blacklist_creators.json"
def _get(url, ttl=600, **p):
    k = url+json.dumps(p, sort_keys=True)
    if k in _c and time.time()-_c[k][0] < ttl: return _c[k][1]
    for i in range(3):
        try:
            if "jup.ag" in url: import jupr; r = jupr.request("GET", url, prio_=2, params=p or None, headers=H, timeout=15)
            else: r = requests.get(url, params=p or None, headers=H, timeout=15)
            if r.status_code == 429: time.sleep(2+3*i); continue
            r.raise_for_status(); _c[k] = (time.time(), r.json()); return _c[k][1]
        except Exception: time.sleep(1)
    return None
def verified():
    d = _get("https://lite-api.jup.ag/tokens/v2/tag", 6*3600, query="verified") or []
    return {t["id"] for t in d}, {(t.get("symbol") or "").upper() for t in d}
def jup(m):
    d = _get("https://lite-api.jup.ag/tokens/v2/search", 300, query=m) or []
    return next((t for t in d if t.get("id") == m), {})
def rc(m): return _get(f"https://api.rugcheck.xyz/v1/tokens/{m}/report", 600) or {}
import threading
_BL_LOCK = threading.Lock(); _BL_LAST = set()
def blacklist():
    global _BL_LAST
    try: _BL_LAST = set(json.load(open(BL))); return set(_BL_LAST)
    except FileNotFoundError: return set()
    except Exception: return set(_BL_LAST)        # torn read while another thread writes: keep the last good set (fail-closed), never an empty one
def ban(*addrs):
    with _BL_LOCK:                                # bans come from several threads (urgent exits): serialize + atomic write so none is lost
        b = blacklist() | {a for a in addrs if a}
        json.dump(sorted(b), open(BL+".tmp", "w")); os.replace(BL+".tmp", BL)
STABLE = re.compile(r"^(W?USD|USDT|USDC|DAI|PYUSD|EURC|UDT|USTC?)")
def check(m, sym, price, c=None, roundtrip=None):
    c = c or {}; f = []; S = (sym or "").upper()
    vid, vsym = verified(); j = jup(m); r = rc(m)
    if m in vid: return []                                                    # Jupiter-verified mint
    if not r and not j: f.append("scam_data_unavailable")                     # fail-closed: with neither RugCheck nor Jupiter data every check below would silently pass
    try: px = float(price)
    except Exception: px = 0
    if STABLE.match(S) and abs(px-1) > 0.03: f.append("fake_stable")
    if S in vsym or S.lstrip("$W") in vsym and len(S) >= 3: f.append("clone_ticker")
    tf = (r.get("transferFee") or {}).get("pct") or 0
    if tf > c.get("max_sell_tax_pct", 3): f.append(f"sell_tax{tf}")
    if roundtrip is not None and roundtrip > c.get("max_roundtrip_loss_pct", 6): f.append(f"honeypot_rt{roundtrip:.1f}")
    lp = max([(mk.get("lp") or {}).get("lpLockedPct") or 0 for mk in r.get("markets") or []] or [0])
    if r and lp < c.get("min_lp_locked_pct", 90): f.append(f"lp_unlocked{lp:.0f}")
    sup = float((r.get("token") or {}).get("supply") or 0)/10**((r.get("token") or {}).get("decimals") or 6)
    dev_pct = (r.get("creatorBalance") or 0)/sup*100 if sup else 0
    if dev_pct > c.get("max_dev_pct", 5): f.append(f"dev_holds{dev_pct:.0f}%")
    au = j.get("audit") or {}
    if (au.get("devMints") or 0) >= c.get("max_dev_mints", 20): f.append(f"serial_dev{au['devMints']}")
    ins = r.get("graphInsidersDetected") or 0
    if ins >= c.get("max_insiders", 5): f.append(f"insiders{ins}")
    if (au.get("topHoldersPercentage") or 0) > c.get("max_top_holders_pct", 35): f.append(f"concentrated{au['topHoldersPercentage']:.0f}%")
    s24 = j.get("stats24h") or {}; s1 = j.get("stats1h") or {}
    if j and (j.get("organicScore") or 0) < c.get("min_organic_score", 10): f.append(f"wash_organic{j.get('organicScore') or 0:.0f}")
    tx = (s1.get("numBuys") or 0)+(s1.get("numSells") or 0); tr = s1.get("numTraders") or s1.get("numOrganicBuyers") or 0
    if tx > 200 and tr and tr/tx < c.get("min_trader_tx_ratio", 0.08): f.append(f"wash_traders{tr}/{tx}")
    ca = j.get("createdAt") or (j.get("firstPool") or {}).get("createdAt")
    if ca:
        import datetime as dt
        age = (time.time()-dt.datetime.fromisoformat(ca.replace("Z", "+00:00")).timestamp())/3600
        if age < c.get("min_age_h", 1): f.append(f"too_new{age:.1f}h")
    if (r.get("tokenMeta") or {}).get("mutable"): f.append("mutable_meta")
    if r.get("mintAuthority"): f.append("mint_auth")
    if r.get("freezeAuthority"): f.append("freeze_auth")
    if (r.get("score_normalised") or 0) > c.get("max_rugcheck_score", 60): f.append(f"rc_score{r['score_normalised']}")
    if r.get("rugged"): f.append("rugged")
    bl = blacklist()
    if r.get("creator") in bl or j.get("dev") in bl: f.append("blacklisted_creator")
    return f
