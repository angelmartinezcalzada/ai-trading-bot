"""Solana memecoin module (paper by default). 4 agents in one loop:
 Scanner  -> new/trending pools from GeckoTerminal + DexScreener (profiles/boosts), enriched via DexScreener pairs
 Filters  -> liquidity, RugCheck (mint/freeze authority, top10 holders ex-pools, LP locked, rugged/creator history, transfer fee),
             honeypot check = Jupiter sell-route quote + round-trip loss
 Analyst  -> score 0-100 (vol/liq, buy/sell, holder growth, momentum, age, socials)
 Executor -> simulated Jupiter quotes (real price impact) + network/priority fees; live = stub that refuses (no keys used)
 Risk     -> stop, trailing, max hold, max positions, daily kill switch
Every candidate + filter result is appended to candidates_solana.jsonl for forward edge evaluation."""
import os, sys, time, json, csv, logging, datetime as dt, requests, threading
import director   # the memebot's own decision authority (only tightens: plays, windows, size, EV floor, exit profile)
log = logging.getLogger("meme")
EX = "solana"; USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"; SOL = "So11111111111111111111111111111111111111112"
STABLES = {"USDT", "USDC", "USDS", "PYUSD", "USDG", "USD1", "FDUSD", "USDE", "DAI", "EURC", "JUPSOL", "MSOL", "JITOSOL", "BSOL", "INF", "WSOL", "SOL", "CBBTC", "WBTC", "WETH"}
H = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
ATA_RENT_SOL = 0.00203928          # rent-exempt minimum of an SPL token account (paid on the first buy of a mint, reclaimable only by closing the account)
RETRY_4XX = {408, 425, 429}          # every other 4xx is a definitive answer (e.g. RugCheck 400 "unable to generate report")
def get(url, timeout=15, retries=3, **p):
    """GET json with retries on timeouts/5xx/429 only. A 4xx (other than 408/425/429) returns None at once: retrying a
    RugCheck 400 three times with 15 s timeouts is what made a 60-token scan take 650-780 s on 2026-10-31."""
    for i in range(retries):
        try:
            if "jup.ag" in url:
                import jupr; r = jupr.request("GET", url, cache_s=5 if "/quote" in url else 20, params=p or None, headers=H, timeout=timeout)
            else: r = requests.get(url, params=p or None, headers=H, timeout=timeout)
            if r.status_code == 429: time.sleep(2+3*i); continue
            if 400 <= r.status_code < 500 and r.status_code not in RETRY_4XX:
                log.debug("GET %s -> %s (no retry)", url, r.status_code); return None
            r.raise_for_status(); return r.json()
        except Exception as e:
            if i == retries-1: log.debug("GET fail %s %s", url, e)
            time.sleep(1)
    return None
def now_s(): return dt.datetime.now().strftime("%H:%M:%S")
import re as _re
import scam
def stable_fake(sym, px):
    """tickers that imitate stablecoins (USDF, USDP, UDTF...) but don't trade at ~$1"""
    if not _re.match(r"^(W?USD|USDT|USDC|DAI|PYUSD|EURC|UDT|USTC?)", (sym or "").upper()): return False
    try: return abs(float(px)-1) > 0.03
    except Exception: return True

def trail_exit(x, p, c):
    """TikTok mode: hard stop -hard_stop_pct net of fees from cost; exit when price falls trail_pct_tt% from peak."""
    net = x*p["raw"]/10**p["dec"]/p["cost"]-1
    if net <= -c.get("hard_stop_pct", 6)/100: return f"hard_stop net={net*100:+.1f}%"
    if x <= p["best"]*(1-c.get("trail_pct_tt", 12)/100) and p["best"] > p.get("entry", x): return f"trail12 peak={p['best']:.6g} net={net*100:+.1f}%"
    return None

class Meme:
    def __init__(s, cfg, live=False):
        s.root = cfg; s.live = live; s.cfg_path = cfg.get("_path", "config.json"); s.mt = 0; s.reload()
        s.wallet = None; tag = f"{EX}_{'live' if live else 'paper'}"; s.state_file, s.csv = f"state_{tag}.json", f"trades_{tag}.csv"
        s.cash = s.c["starting_equity"]; s.pos = {}; s.trades = []; s.seen = {}; s.dead = {}; s.day = dt.date.today().isoformat(); s.day_start = s.cash; s.halted = False
        s.signals, s.cands, s.paused, s.eq_t, s.scan_t, s.sol, s.sol24, s.decisions = [], [], False, 0, 0, 0.0, 0.0, []
        import brain; s.brain = brain.Brain(); s.learn_t = 0
        if os.path.exists(s.state_file):
            st = json.load(open(s.state_file)); s.__dict__.update({k: st[k] for k in ("cash", "pos", "trades", "seen", "day", "day_start", "halted", "dead") if k in st})
        if not os.path.exists(s.csv):
            with open(s.csv, "w", newline="") as f: csv.writer(f).writerow("time,exchange,symbol,side,price,qty,fee,pnl,reason,equity".split(","))
    def reload(s):
        try:
            mt = os.path.getmtime(s.cfg_path)
            if mt != s.mt: s.c_base = json.load(open(s.cfg_path))["exchanges"][EX]; s.mt = mt
        except Exception as e: log.warning("cfg reload %s (keeping previous config)", e); return
        s.c = Meme.apply_director(s, getattr(s, "c_base", getattr(s, "c", {})))
        _c = s.c
        if _c.get("exit_mode") == "trail" and getattr(s, "_trail_logged", None) != (_c.get("size_pct"), _c.get("hard_stop_pct"), _c.get("trail_pct_tt")):
            s._trail_logged = (_c.get("size_pct"), _c.get("hard_stop_pct"), _c.get("trail_pct_tt")); log.warning("[solana] EXIT MODE trail: size=%s%% hard_stop=-%s%% trail=%s%% from peak", *s._trail_logged)
    def apply_director(s, base):
        """effective config = config.json tightened by director_state.json (director.apply_director: never looser). Cached per state-file
        mtime and 10-minute bucket; a missing / stale / corrupt state means the base config, logged once."""
        if base.get("director_enabled", True) is False: return dict(base)   # owner's off switch: the Director computes and logs but never commands
        try:
            key = (os.path.getmtime("director_state.json") if os.path.exists("director_state.json") else None, id(base), int(time.time()//600))
            if getattr(s, "_dir_key", None) == key and getattr(s, "_dir_c", None) is not None: return s._dir_c
            st, why = director.load_state(".")
            c, changes = director.apply_director(base, st)
            if changes or (st is None and getattr(s, "_dir_why", None) != why) or (st and st.get("shadow") and getattr(s, "_dir_why", None) != "shadow"):
                log.warning("[solana] DIRECTOR %s%s", "shadow (calculado, no aplicado)" if st and st.get("shadow") else why, (": " + ", ".join(f"{k} {a}->{b}" for k, a, b in changes)) if changes else "")
            s._dir_key, s._dir_c, s._dir_why = key, c, ("shadow" if st and st.get("shadow") else why); return c
        except Exception as e: log.warning("director apply %s (base config)", e); return dict(base)
    def director_cycle(s):
        """hourly (learn thread): measure the evidence and write director_state.json; reload() applies it once out of shadow"""
        data = None
        try: data = s.brain.build_dataset(dict(s.c), max_fetch=0)
        except Exception as e: log.info("[director] dataset: %s", e)
        director.compute(".", dict(getattr(s, "c_base", s.c)), s.equity(), s.sol or 0.0, data=data)
    def buys_today(s):
        """number of BUY rows of today in this mode's ledger (director daily cap); cached 60 s"""
        if time.time()-getattr(s, "_bt_t", 0) < 60: return getattr(s, "_bt_n", 0)
        n, day = 0, dt.date.today().isoformat()
        try:
            for r in csv.reader(open(s.csv)):
                if len(r) > 3 and r[0].startswith(day) and r[3] == "BUY": n += 1
        except Exception: pass
        s._bt_t, s._bt_n = time.time(), n; return n
    def ata_sweep(s):
        """live: close the token accounts of fully-sold mints so their rent (0.00204 SOL each) returns to the wallet. Daemon thread, never a
        mint still held, 3 attempts per mint, result appended to research/ata_close.jsonl (feeds director.rent_lost_prob)."""
        q = s.__dict__.setdefault("_ata_q", {})
        if not s.live or not q or not s.c.get("ata_autoclose", True): return
        thr = getattr(s, "_ata_thr", None)
        if thr is not None and thr.is_alive(): return
        due = [m for m, v in q.items() if time.time()-v["t"] > 20 and m not in s.pos]
        if not due: return
        def _run(mints=due):
            try:
                import live_sol; r = live_sol.close_empty_atas(dry_run=False, only=set(mints), skip=set(s.pos))
                failed = {m for m, _ in r["failed"]}
                for m in mints:
                    if m in failed:
                        q[m]["n"] += 1; q[m]["t"] = time.time()
                        if q[m]["n"] >= 3: q.pop(m, None); log.warning("[solana] ATA %s not closed after 3 attempts (rent stays locked)", m[:8])
                    else: q.pop(m, None)
                if r["closed"]: log.info("[solana] ATA closed %d account(s), SOL back %s", r["closed"], r["sol_recovered"])
                os.makedirs("research", exist_ok=True)
                with open("research/ata_close.jsonl", "a") as f: f.write(json.dumps({"t": time.time(), **{k: v for k, v in r.items() if k != "mints"}})+"\n")
            except Exception as e: log.warning("[solana] ATA sweep %s", e)
        s._ata_thr = threading.Thread(target=_run, daemon=True); s._ata_thr.start()
    def save(s):
        st = {k: getattr(s, k) for k in ("cash", "pos", "trades", "seen", "day", "day_start", "halted", "dead")}
        json.dump(st, open(s.state_file+".tmp", "w")); os.replace(s.state_file+".tmp", s.state_file)
    # ---------------- Scanner ----------------
    DEXES = ["pumpswap", "meteora-damm-v2", "raydium-launchlab", "raydium", "meteora", "pump-fun", "raydium-clmm"]
    def gk(s, path, **p):
        # GeckoTerminal free tier ~30 req/min -> global spacing 2.1s
        w = 2.1-(time.time()-getattr(s, "_gk_t", 0))
        if w > 0: time.sleep(w)
        s._gk_t = time.time(); return get("https://api.geckoterminal.com/api/v2/networks/solana/" + path, **p) or {}
    def scan(s):
        mints, s.gpool, s.gctx = {}, getattr(s, "gpool", {}), []
        s._rot = getattr(s, "_rot", -1)+1
        paths = [("new_pools", {"page": 1}), ("trending_pools", {"duration": "5m"}), ("trending_pools", {"duration": "1h"}),
                 (f"dexes/{s.DEXES[s._rot % len(s.DEXES)]}/pools", {"page": 1})]
        paths.append(("pools", {"page": 1, "sort": "h24_volume_usd_desc"}))   # established, liquid pools (src widening 2026-10-31)
        if s._rot % 2 == 0: paths.append(("new_pools", {"page": 2}))
        else: paths.append(("trending_pools", {"duration": "6h"}))
        for path, prm in paths:
            for p in s.gk(path, **prm).get("data", []):
                m = p["relationships"]["base_token"]["data"]["id"].split("_", 1)[1]
                if m in (SOL, USDC): continue
                mints[m] = "gecko_" + path.replace("dexes/", "").replace("/pools", "")
                s.gpool[m] = {"tx": p["attributes"].get("transactions") or {}, "dex": p["relationships"]["dex"]["data"]["id"], "t": time.time()}
                s.gctx.append({"name": p["attributes"].get("name", ""), "sym": "", "new": path == "new_pools", "vol_h1": float((p["attributes"].get("volume_usd") or {}).get("h1") or 0)})
        for u, src in (("https://api.dexscreener.com/token-profiles/latest/v1", "dex_profiles"), ("https://api.dexscreener.com/token-boosts/latest/v1", "dex_boosts"),
                       ("https://api.dexscreener.com/token-boosts/top/v1", "dex_boosts_top")):
            for t in get(u) or []:
                if t.get("chainId") == "solana": mints.setdefault(t["tokenAddress"], src)
        for u, src in (("https://lite-api.jup.ag/tokens/v2/toptrending/5m?limit=40", "jup_trend5m"), ("https://lite-api.jup.ag/tokens/v2/toptrending/1h?limit=40", "jup_trend1h"),
                       ("https://lite-api.jup.ag/tokens/v2/toporganicscore/5m?limit=40", "jup_organic5m"), ("https://lite-api.jup.ag/tokens/v2/toptraded/5m?limit=40", "jup_traded5m"),
                       ("https://lite-api.jup.ag/tokens/v2/toptraded/1h?limit=100", "jup_traded1h"), ("https://lite-api.jup.ag/tokens/v2/toptraded/24h?limit=100", "jup_traded24h"),
                       ("https://lite-api.jup.ag/tokens/v2/toporganicscore/24h?limit=100", "jup_organic24h"), ("https://lite-api.jup.ag/tokens/v2/toptrending/24h?limit=100", "jup_trend24h")):
            for t in get(u) or []:
                if isinstance(t, dict) and t.get("id") and t["id"] not in (SOL, USDC) and str(t.get("symbol", "")).upper() not in STABLES: mints.setdefault(t["id"], src)
        for m in list(s.pos) + [k for k, v in s.seen.items() if v.get("watch", 0) > time.time()]: mints.setdefault(m, "watchlist")
        try:                                                     # insider TOP priority: smart-money tokens enter the scan universe directly
            st_ = s.ins_st()
            for k, T in sorted((st_.get("tokens") or {}).items(), key=lambda x: -(x[1].get("score") or 0))[:30]:
                if (T.get("score") or 0) >= 5 or (T.get("elite") or 0) >= 3: mints[k] = "insider"
        except Exception as e: log.debug("insider universe %s", e)
        s.gpool = {k: v for k, v in s.gpool.items() if time.time()-v["t"] < 3600}
        return mints
    def pairs(s, mints):
        out, ml = {}, list(mints)
        for i in range(0, len(ml), 30):
            for p in get("https://api.dexscreener.com/tokens/v1/solana/" + ",".join(ml[i:i+30])) or []:
                m = p["baseToken"]["address"]
                if m in mints and (m not in out or (p.get("liquidity") or {}).get("usd", 0) > (out[m].get("liquidity") or {}).get("usd", 0)): out[m] = p
        return out
    # ---------------- Filters ----------------
    def rug(s, m):
        r = get(f"https://api.rugcheck.xyz/v1/tokens/{m}/report", timeout=s.c.get("rc_timeout_s", 8), retries=2)
        if not r: return s.rug_fallback(m)
        try: return s._rug_parse(r)
        except Exception as e: log.warning("rug parse %s %s", m, e); return None   # fail-closed (like rug_fallback); one bad report must not abort the scan
    def _rug_parse(s, r):
        pools = set()
        for mk in r.get("markets") or []:
            for k in ("pubkey", "liquidityA", "liquidityB", "liquidityAAccount", "liquidityBAccount"): 
                v = mk.get(k); pools.add(v if isinstance(v, str) else None)
        known = {a for a, v in (r.get("knownAccounts") or {}).items() if v.get("type") in ("AMM", "LOCKER")}
        hold = [h for h in r.get("topHolders") or [] if h.get("address") not in pools and h.get("owner") not in known and h.get("owner") not in pools]
        lp = [(mk.get("lp") or {}).get("lpLockedPct") or 0 for mk in r.get("markets") or []]
        return {"mint_auth": r.get("mintAuthority"), "freeze_auth": r.get("freezeAuthority"), "top10": round(sum(h.get("pct", 0) for h in hold[:10]), 2),
                "lp_locked": round(max(lp) if lp else 0, 1), "rugged": bool(r.get("rugged")), "score_norm": r.get("score_normalised"),
                "holders": r.get("totalHolders") or 0, "dec": (r.get("token") or {}).get("decimals") or 6, "creator": r.get("creator"), "creator_bal": r.get("creatorBalance") or 0, "supply": (r.get("token") or {}).get("supply") or 0, "verified": bool((r.get("verification") or {}).get("jup_verified") or (r.get("verification") or {}).get("jup_strict")), "fee_pct": (r.get("transferFee") or {}).get("pct", 0) or 0, "insiders": r.get("graphInsidersDetected") or 0,
                "danger": [x["name"] for x in r.get("risks") or [] if x.get("level") == "danger"],
                "creator_rugs": sum(1 for t in r.get("creatorTokens") or [] if t.get("rugged")) if isinstance(r.get("creatorTokens"), list) else 0}
    def rug_fallback(s, m):
        """RugCheck down -> GoPlus + on-chain RPC. Fail-closed: anything undeterminable -> treated as failing."""
        try:
            g = (get("https://api.gopluslabs.io/api/v1/solana/token_security", contract_addresses=m) or {}).get("result") or {}
            g = g.get(m)
            if not g or not g.get("holder_count"): return None
            import live_sol
            ai = (live_sol.rpc("getAccountInfo", [m, {"encoding": "jsonParsed"}]) or {}).get("value") or {}
            info = ((ai.get("data") or {}).get("parsed") or {}).get("info") or {}
            if not info: return None
            st = lambda k: str((g.get(k) or {}).get("status", "1")) if isinstance(g.get(k), dict) else "1"
            danger = []
            if st("balance_mutable_authority") != "0": danger.append("balance_mutable")
            if st("closable") != "0": danger.append("closable")
            if str(g.get("default_account_state", "1")) != "1": danger.append("default_frozen")
            if st("default_account_state_upgradable") != "0": danger.append("state_upgradable")
            if str(g.get("non_transferable", "1")) != "0": danger.append("non_transferable")
            if g.get("transfer_hook") or st("transfer_hook_upgradable") != "0": danger.append("transfer_hook")
            if st("transfer_fee_upgradable") != "0": danger.append("fee_upgradable")
            if any(x.get("malicious_address") for x in (g.get("metadata_mutable") or {}).get("metadata_upgrade_authority") or []): danger.append("malicious_authority")
            fee = g.get("transfer_fee") or {}
            fee_pct = 99 if fee else 0      # any Token-2022 transfer-fee config -> reject (fail-closed)
            dex = sorted(g.get("dex") or [], key=lambda d: -float(d.get("tvl") or 0))
            top = dex[0] if dex else {}
            lp = float(top["burn_percent"]) if top.get("type") == "Standard" and top.get("burn_percent") is not None else 0.0   # CLMM/unknown -> not locked
            excl = {d.get("id") for d in dex} | {"5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1", "GpMZbSM2GgvTKHJirzeGfMFoaZ8UR2X7F4v8vHTvxFbL"}
            hold = [h for h in g.get("holders") or [] if h.get("account") not in excl and not h.get("is_locked")]
            top10 = round(sum(float(h.get("percent") or 0) for h in hold[:10]) * 100, 2)
            if len(g.get("holders") or []) < 10: return None
            mutable_meta = str((g.get("metadata_mutable") or {}).get("status", "1")) != "0"
            sc = 0 if not danger else 100
            sc += 5 if mutable_meta else 0
            return {"mint_auth": info.get("mintAuthority") or (None if st("mintable") == "0" else "goplus_mintable"),
                    "freeze_auth": info.get("freezeAuthority") or (None if st("freezable") == "0" else "goplus_freezable"),
                    "top10": top10, "lp_locked": round(lp, 1), "rugged": False, "score_norm": sc, "holders": int(g["holder_count"]),
                    "dec": info.get("decimals") or 6, "creator": None, "creator_bal": 0, "supply": float(g.get("total_supply") or 0),
                    "verified": bool(g.get("trusted_token")), "fee_pct": fee_pct, "insiders": 0, "danger": danger, "creator_rugs": 0, "src": "goplus+rpc"}
        except Exception as e:
            log.warning("rug fallback %s %s", m, e); return None
    def quote(s, inp, out, amount, slip=300):
        q = get("https://lite-api.jup.ag/swap/v1/quote", inputMint=inp, outputMint=out, amount=str(int(amount)), slippageBps=slip)
        return q if q and "outAmount" in q else None
    def honeypot(s, *a):
        k = ("honeypot",)+a; C = s.__dict__.setdefault("_ttl", {}); v = C.get(k)
        if v and time.time()-v[0] < 1800: return v[1]
        r = s._honeypot(*a)
        if r[0] is not None or r[1] not in ("no_buy_route", "no_sell_route"): C[k] = (time.time(), r)   # a missing quote may be a Jupiter outage: veto now, but do not cache it for 30 min
        return r
    def _honeypot(s, m, usd):
        """buy quote USDC->token, then sell those tokens back -> round-trip loss % (price impact both legs + any tax)."""
        b = s.quote(USDC, m, usd*1e6)
        if not b: return None, "no_buy_route"
        sl = s.quote(m, USDC, int(b["outAmount"]))
        if not sl: return None, "no_sell_route"
        return (1-int(sl["outAmount"])/1e6/usd)*100, b
    # ---------------- Analyst ----------------
    def whales(s, *a):
        k = ("whales",)+a; C = s.__dict__.setdefault("_ttl", {}); v = C.get(k)
        if v and time.time()-v[0] < 300: return v[1]
        r = s._whales(*a); C[k] = (time.time(), r); return r
    def _whales(s, pair):
        """smart-money proxy: large buys (>= whale_usd) in last 10 min from GeckoTerminal trades; also counts repeat sniper wallets"""
        d = s.gk(f"pools/{pair}/trades").get("data", [])
        cut = time.time()-600; big = 0; bigsell = 0; wallets = {}
        for t in d:
            a = t["attributes"]; ts = dt.datetime.fromisoformat(a["block_timestamp"].replace("Z", "+00:00")).timestamp()
            if ts < cut: continue
            v = float(a.get("volume_in_usd") or 0); wallets[a["tx_from_address"]] = wallets.get(a["tx_from_address"], 0)+1
            if v >= s.c["whale_usd"]: big += a["kind"] == "buy"; bigsell += a["kind"] == "sell"
        return big, bigsell, sum(1 for v in wallets.values() if v >= 5)   # wallets with >=5 trades in 10min ~ bots
    def score(s, p, rc, m):
        c = s.c; liq = (p.get("liquidity") or {}).get("usd") or 0; v = p.get("volume") or {}; tx = p.get("txns") or {}; pc = p.get("priceChange") or {}
        b1, s1 = (tx.get("h1") or {}).get("buys", 0), (tx.get("h1") or {}).get("sells", 0)
        b5, s5 = (tx.get("m5") or {}).get("buys", 0), (tx.get("m5") or {}).get("sells", 0)
        age_h = (time.time()*1000-(p.get("pairCreatedAt") or 0))/3.6e6
        vl = (v.get("h24") or 0)/liq if liq else 0; prev = s.seen.get(m, {}); parts = {}
        parts["vol_liq"] = min(12, vl*2.4)
        parts["buy_press"] = min(12, max(0, (b1/(s1+1)-0.8)*15)) if b1+s1 >= 20 else 0
        h1, m5 = pc.get("h1") or 0, pc.get("m5") or 0
        parts["momentum"] = 12 if 3 <= h1 <= 60 and m5 >= 0 else 6 if 0 < h1 < 120 else 0
        vel = (b5+s5)/max(1, (b1+s1)/12)                                    # txn velocity vs 1h avg
        parts["velocity"] = min(8, max(0, (vel-1)*6))
        g = s.gpool.get(m, {}).get("tx", {})
        ub5, ub1 = (g.get("m5") or {}).get("buyers", 0), (g.get("h1") or {}).get("buyers", 0)
        parts["uniq_buyers"] = min(10, max(0, (ub5/max(1, ub1/12)-1)*6)) if ub1 >= 20 else 0
        hg = rc["holders"]/prev["holders"]-1 if prev.get("holders") else 0
        parts["holder_growth"] = min(10, max(0, hg*120)) if prev.get("holders") else min(5, rc["holders"]/500)
        lg = liq/prev["liq"]-1 if prev.get("liq") else 0
        parts["liq_growth"] = min(6, max(-6, lg*60))
        tc = rc["top10"]-prev["top10"] if prev.get("top10") is not None else 0
        parts["concentration"] = min(4, max(-8, -tc*2))                     # concentration falling = good
        parts["age"] = 8 if 1 <= age_h <= 72 else 4 if age_h <= 240 else 0
        info = p.get("info") or {}; soc = info.get("socials") or []; types = {x.get("type") for x in soc}
        parts["socials"] = min(8, 3*("twitter" in types) + 3*("telegram" in types) + 2*bool(info.get("websites"))) + (4 if rc.get("verified") else 0)
        parts["insiders"] = -min(15, rc["insiders"]*3)                      # bundled / sniper networks (RugCheck)
        cb = rc["creator_bal"]/rc["supply"]*100 if rc.get("supply") else 0
        parts["dev_hold"] = -8 if cb > 5 else 0
        wb = ws = bots = 0
        if p.get("pairAddress") and sum(parts.values()) >= c["min_score"]-15:   # only spend API calls on near-qualifiers
            wb, ws, bots = s.whales(p["pairAddress"])
        parts["whales"] = min(10, wb*3) - min(10, ws*3)
        parts["bots"] = -min(6, bots)
        sc = round(max(0, min(100, sum(parts.values()))), 1)
        comp = dict(liq=round(liq), vol_liq=round(vl, 2), b_s=f"{b1}/{s1}", h1=h1, m5=m5, age_h=round(age_h, 1), vel=round(vel, 2), ub5=ub5, ub1=ub1,
                    holder_g=round(hg*100, 1), liq_g=round(lg*100, 1), top10_chg=round(tc, 2), whale_buys=wb, whale_sells=ws, bot_wallets=bots,
                    creator_pct=round(cb, 2), parts={k: round(v, 1) for k, v in parts.items()})
        return sc, comp
    # ---------------- LIVE wallet (auto: >= live_min_sol SOL in solana_wallet.json) ----------------
    def wallet_check(s):
        """every 60s: read the hot wallet; switch to LIVE automatically once it holds >= live_min_sol (and no KILL_solana)."""
        if time.time()-getattr(s, "wallet_t", 0) < 60 or not os.path.exists("solana_wallet.json"): return
        s.wallet_t = time.time()
        try:
            import live_sol; bal = live_sol.sol_balance(); s.wallet = dict(addr=live_sol.address(), sol=bal, usd=bal*(s.sol or 0), t=time.time())
        except Exception as e: log.warning("[solana] wallet read %s", e); return
        if not s.live and bal >= s.c.get("live_min_sol", 0.05) and not os.path.exists("KILL_solana"): s.go_live()
        elif s.live: s.reconcile()
    def go_live(s):
        s.save(); log.warning("[solana] >>> SWITCHING TO REAL MONEY: wallet %s holds %.4f SOL", s.wallet["addr"], s.wallet["sol"])
        s.live = True; s.state_file, s.csv = "state_solana_live.json", "trades_solana_live.csv"
        s.pos, s.trades, s.halted = {}, [], False
        if os.path.exists(s.state_file):
            st = json.load(open(s.state_file)); s.__dict__.update({k: st[k] for k in ("pos", "trades", "day", "day_start", "halted", "seen", "dead") if k in st})   # seen = loss/re-entry cooldowns (were lost on every restart)
        if not os.path.exists(s.csv):
            with open(s.csv, "w", newline="") as f: csv.writer(f).writerow("time,exchange,symbol,side,price,qty,fee,pnl,reason,equity".split(","))
        s.reconcile(adopt=True)
        if not os.path.exists(s.state_file) or s.day != dt.date.today().isoformat(): s.day, s.day_start = dt.date.today().isoformat(), s.equity()
        s.save()
    def reconcile(s, adopt=False):
        """LIVE: cash = SOL above the fee reserve; positions follow real on-chain token balances (drop missing, adopt unknown >= $1)."""
        import live_sol
        try: bal = live_sol.sol_balance(); tb = live_sol.token_balances()
        except Exception as e: log.warning("[solana] reconcile %s", e); return
        s.wallet = dict(addr=live_sol.address(), sol=bal, usd=bal*(s.sol or 0), t=time.time())
        s.cash = max(0.0, bal-s.c.get("sol_fee_reserve", 0.02))*(s.sol or 0)
        for m in list(s.pos):
            if m not in tb:
                s.pos[m]["miss"] = s.pos[m].get("miss", 0)+1   # RPC can return partial lists: drop only after 3 consecutive misses
                if s.pos[m]["miss"] >= 3: log.warning("[solana] reconcile: %s no longer in wallet -> dropped", s.pos[m]["sym"]); s.pos.pop(m)
                continue
            s.pos[m]["miss"] = 0
            if False: pass
            elif tb[m][0] != s.pos[m]["raw"]:
                k = tb[m][0]/max(1, s.pos[m]["raw"]); s.pos[m]["cost"] *= k; s.pos[m]["raw"] = tb[m][0]
        if not adopt and time.time()-getattr(s, "_adopt_t", 0) > 300: s._adopt_t = time.time(); adopt = True   # periodic re-adopt of orphans
        if adopt:
            for m, (raw, dec) in tb.items():
                if m in s.pos or m == USDC or m in getattr(s, "dead", {}): continue   # written-off rugs are never re-adopted
                q = s.quote(m, USDC, raw, 500)
                v = int(q["outAmount"])/1e6 if q else 0
                if v >= 0.5:
                    px = v/(raw/10**dec); sym_ = m[:4]
                    try:   # recover entry from our own REAL BUY record
                        for row in csv.reader(open(s.csv)):
                            if len(row) > 8 and row[3] == "BUY" and "REAL" in row[8] and abs(float(row[5])-raw/10**dec) < 1e-6*max(1, raw/10**dec): sym_ = row[2]; v = float(row[4])*float(row[5])+float(row[6]); px = float(row[4])
                    except Exception: pass
                    s.pos[m] = dict(sym=sym_, raw=raw, dec=dec, entry=px, best=px, mark0=px, mark=int(q['outAmount'])/1e6/(raw/10**dec), cost=v, t=time.time(), impact=0, score=0, pair=None, adopted=True, partial=False, stop_pct=s.c["stop_pct"])
                    log.warning("[solana] reconcile: adopted on-chain %s value %.2f USD", m, v)
    def adapt(s, sc, lv, I, smart_flags, risk_off, btc_on, size_mult=1.0):
        """adaptive per-trade risk: score x regime x volatility x insider -> risk budget, stop, per-trade loss limit (only hard caps: 5%/day + position cap)"""
        f_sc = 0.6 + max(0, min(1, (sc-45)/55))*0.8
        f_rg = (0.6 if risk_off else 1.0)*(0.8 if btc_on is False else 1.0)*max(0.5, min(1.3, size_mult))
        f_vo = 1/max(0.7, min(1.5, lv.get("vol_mult", 1.0) if lv else 1.0))
        f_in = 1.0
        if I.get("elite", 0) >= 2: f_in = 1.4
        elif I.get("conv", 0) >= 3: f_in = 1.25
        if I.get("sells", 0) >= 3 or set(smart_flags) & {"dev_selling", "whale_dump", "early_exit"}: f_in = 0.5
        elif "smart_buy" in smart_flags or "whale_accum" in smart_flags: f_in *= 1.1
        risk = min(0.01, max(0.002, s.c.get("risk_per_trade", 0.005)*f_sc*f_rg*f_vo*f_in))
        stop = (lv or {}).get("stop_pct", s.c["stop_pct"])*(1.15 if f_in > 1 else 0.85 if f_in < 1 else 1.0)*(0.9 if risk_off else 1.0)
        stop = min(s.c.get("max_stop_pct", 0.15)*1.5, max(0.04, stop))
        mtl = min(0.03, max(0.004, risk*1.6))
        return dict(risk=round(risk, 5), stop_pct=round(stop, 4), mtl=round(mtl, 5), f=dict(score=round(f_sc, 2), regime=round(f_rg, 2), vol=round(f_vo, 2), insider=round(f_in, 2)))
    # ---------------- Executor ----------------
    def net_fee_usd(s): return (s.c["priority_fee_sol"] + 0.000005)*(s.sol or 150)
    def coin_levels(s, pair, px, rt):
        """per-coin levels from this coin's own 1m bars: ATR, structure, volume profile; vol multiplier for v3.1 exits"""
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "research")); import levels as LV
        B = s.__dict__.setdefault("_bars", {}); d = B.get(pair) if pair in B and time.time()-B[pair][0] < 300 else None
        d = d[1] if d else s.gk(f"pools/{pair}/ohlcv/minute", aggregate=1, limit=150, currency="usd")   # one rate-limited try, cached 5 min
        if not d or not (d.get("data") or {}).get("attributes"):
            return s.levels_fallback(pair, px, rt)        # GT 429/empty: volatility from DexScreener instead of the flat 6% stop
        B[pair] = (time.time(), d)
        bars = sorted(x[:6] for x in d["data"]["attributes"]["ohlcv_list"]); bars = [b for b in bars if b[0] < time.time()-30] or bars
        if len(bars) < 5: return s.levels_fallback(pair, px, rt)
        Lp = s.c.get("dyn_levels", {"ks": 4, "ktp": 15, "ktr": 3}); L = LV.levels(bars, px, Lp, rt/100)
        if not L.get("sup") or L["sup"] >= px*0.999 or not L.get("atr"): return s.levels_fallback(pair, px, rt)   # degenerate history (sup==entry)
        atrp = L["atr"]/px; mult = min(1.5, max(0.7, (atrp/s.c.get("med_atrp", 0.01328))**0.75))
        sp = max(s.c["stop_pct"]*mult, min(s.c["stop_pct"]*mult*1.5, s.c["stop_pct"]*mult+rt/100))
        return {"atr_pct": round(atrp*100, 2), "sup": L["sup"], "res": L["res"], "poc": L["poc"], "swing_lo": L["swing_lo"], "swing_hi": L["swing_hi"],
                "dyn_stop": L["stop"], "dyn_tp1": L["tp1"], "vol_mult": round(mult, 2), "stop_pct": round(sp, 4), "tp_pct": round(s.c["partial_tp_pct"]*mult, 4),
                "act_pct": round(s.c["trail_activate_pct"]*mult, 4), "trail_w": round(s.c["trail_pct"]*mult, 4), "runner_pct": round(s.c["runner_trail_pct"]*mult, 4),
                "mode": s.c.get("exit_mode", "v31")}
    def levels_fallback(s, pair, px, rt):
        pr = (get(f"https://api.dexscreener.com/latest/dex/pairs/solana/{pair}") or {}).get("pairs") or [{}]
        ch = (pr[0] or {}).get("priceChange") or {}
        atrp = max(0.003, abs(float(ch.get("m5") or 0))/100/5**0.5, abs(float(ch.get("h1") or 0))/100/60**0.5)
        mult = min(1.5, max(0.7, (atrp/s.c.get("med_atrp", 0.01328))**0.75))
        sp = max(s.c["stop_pct"]*mult, min(s.c["stop_pct"]*mult*1.5, s.c["stop_pct"]*mult+rt/100))
        log.info("[solana] levels fallback (DexScreener) pair %s: atr~%.2f%% volx=%.2f stop=%.1f%%", pair, atrp*100, mult, sp*100)
        return {"atr_pct": round(atrp*100, 2), "sup": px, "res": 0, "poc": px, "swing_lo": px, "swing_hi": px, "dyn_stop": px*(1-sp), "dyn_tp1": px*(1+s.c["partial_tp_pct"]*mult),
                "vol_mult": round(mult, 2), "stop_pct": round(sp, 4), "tp_pct": round(s.c["partial_tp_pct"]*mult, 4), "act_pct": round(s.c["trail_activate_pct"]*mult, 4),
                "trail_w": round(s.c["trail_pct"]*mult, 4), "runner_pct": round(s.c["runner_trail_pct"]*mult, 4), "mode": s.c.get("exit_mode", "v31"), "fallback": True}
    def apply_levels(s, P, lv):
        P["lv"] = lv
        if s.c.get("exit_mode") == "volscale":
            P.update(stop_pct=lv["stop_pct"] if not P.get("partial") else P.get("stop_pct", 0), tp_pct=lv["tp_pct"], act_pct=lv["act_pct"], trail_w=lv["trail_w"], runner_pct=lv["runner_pct"])
    def buy(s, m, p, sc, why):
        lv0 = None
        if s.c.get("exit_mode") == "volscale":
            try:
                lv0 = s.coin_levels(p.get("pairAddress"), float(p.get("priceUsd") or 0), 2.5)
                A = s.adapt(sc, lv0, s.insider_feat(m), list((getattr(s, "smart", {}).get(m) or {}).get("flags") or []), p.get("_riskoff"), p.get("_btc_on"), p.get("_smult", 1.0)); p["_adapt"] = A
                cap = s.equity()*A["risk"]/A["stop_pct"]          # adaptive risk budget / adaptive stop distance
                p["_size"] = min(p.get("_size") or 1e9, cap, s.equity()*s.c.get("max_position_pct", 0.08), s.cash*0.98)
            except Exception as e: log.info("[solana] pre-levels %s: %s", m, e)
        if s.c.get("exit_mode") == "trail" and p.get("_play") != "pump":   # TikTok mode: fixed % of equity
            p["_size"] = min(p.get("_size") or 1e9, s.equity()*s.c.get("size_pct", 8)/100, s.cash*0.98)
        size = p.get("_size") or min(s.equity()*s.c["position_pct"], s.cash*0.98)
        size = min(size, s.equity()*s.c.get("max_gap_loss_pct", 0.03))   # gap/rug cap: a total wipe-out costs <= 3% equity
        if p.get("_floor") and size < p["_floor"] <= min(s.equity()*s.c.get("max_gap_loss_pct", 0.1), s.cash*0.98): size = p["_floor"]   # live $1 floor
        if size < (s.c.get("live_min_trade_usd", 1) if s.live else 10): return
        q = s.quote(USDC, m, size*1e6, p.get("_slip") or s.c["slippage_bps"])
        if not q: log.info("[solana] buy %s aborted: no quote", m); return
        if s.live: return s.buy_live(m, p, sc, why, size)
        dec = p.get("_dec") or 6; qty = int(q["outAmount"]); fee = s.net_fee_usd(); px = size/(qty/10**dec)
        s.cash -= size+fee; sym = p["baseToken"]["symbol"]
        s.pos[m] = dict(sym=sym, raw=qty, dec=dec, entry=px, best=px, cost=size+fee, t=time.time(), impact=float(q.get("priceImpactPct") or 0)*100, score=sc, pair=p.get("url"))
        sq = s.quote(m, USDC, qty, s.c["slippage_bps"]); x0 = int(sq["outAmount"])/1e6/(qty/10**dec) if sq else px*0.97
        rt = (1-x0/px)*100; P = s.pos[m]
        P.update(mark0=x0, best=x0, rt=rt, stop_pct=max(s.c["stop_pct"], min(s.c["max_stop_pct"], s.c["stop_pct"]+rt/100)), pair_addr=p.get("pairAddress"),
                 liq0=(p.get("liquidity") or {}).get("usd") or 0, creator=(s.seen.get(m, {}).get("rc") or {}).get("creator"), cbal0=(s.seen.get(m, {}).get("rc") or {}).get("creator_bal", 0), partial=False)
        s.post_buy(m, p, P, px, rt, sc, why, fee, qty, dec, sym)
    def post_buy(s, m, p, P, px, rt, sc, why, fee, qty, dec, sym):
        lvtxt = ""
        if p.get("_play") == "pump":
            P["play"] = "pump"; why = "PUMP-PLAY " + why
        try:
            lv = s.coin_levels(p.get("pairAddress"), px, rt); s.apply_levels(P, lv)
            A = p.get("_adapt")
            if A:
                A = s.adapt(sc, lv, s.insider_feat(m), list((getattr(s, "smart", {}).get(m) or {}).get("flags") or []), p.get("_riskoff"), p.get("_btc_on"), p.get("_smult", 1.0))
                P.update(stop_pct=A["stop_pct"], mtl=A["mtl"], adapt=A); lvtxt += f" ADAPT risk={A['risk']*100:.2f}% stop={A['stop_pct']*100:.1f}% maxloss={A['mtl']*100:.2f}% f={A['f']}"
            lvtxt = f" atr={lv['atr_pct']}% volx={lv['vol_mult']} tp={P.get('tp_pct', s.c['partial_tp_pct'])*100:.1f}% trail={P.get('trail_w', s.c['trail_pct'])*100:.1f}%@{P.get('act_pct', s.c['trail_activate_pct'])*100:.1f}% sup={lv['sup']:.6g} res={(lv['res'] or 0):.6g} poc={(lv['poc'] or 0):.6g}"
            open("levels_solana.jsonl", "a").write(json.dumps({"t": now_s(), "sym": sym, "entry": px, **lv}) + "\n")
        except Exception as e: log.info("[solana] levels %s: %s", sym, e)
        if P.get("play") == "pump":   # aggressive: sell before the peak
            c = s.c; P.update(stop_pct=min(P.get("stop_pct", c["stop_pct"]), c.get("pump_stop_pct", 0.06)), act_pct=c.get("pump_trail_act", 0.04), trail_w=c.get("pump_trail_pct", 0.05),
                              tp_pct=c.get("pump_tp_pct", 0.15), runner_pct=c.get("pump_trail_pct", 0.05))
        s.record(sym, "BUY", px, qty/10**dec, fee, 0, f"meme score={sc} {why} impact={P['impact']:.2f}% rt={rt:.2f}% stop={P['stop_pct']*100:.1f}%{lvtxt}")
    def sell(s, m, reason, frac=1.0):
        import threading
        if not hasattr(s, "_slk"): s._slk = threading.RLock()
        if not s._slk.acquire(timeout=5): log.info("[solana] sell %s deferred: another sell in flight", s.pos.get(m, {}).get("sym")); return
        try:
            if m not in s.pos: return
            return s._sell(m, reason, frac)
        finally: s._slk.release()
    def _sell(s, m, reason, frac=1.0):
        import jupr
        with jupr.prio(0): return s._sell0(m, reason, frac)
    def _sell0(s, m, reason, frac=1.0):
        s._pump_sell = s.pos.get(m, {}).get("play") == "pump"
        p = s.pos[m]; raw = p["raw"] if frac >= 1 else int(p["raw"]*frac)
        if p.get("sellfail", 0) >= 3 and time.time()-p.get("fail_last", 0) < min(1800, 30*2**(p["sellfail"]-3)): return   # back-off after repeated failed swaps (frozen ATA / honeypot): 30 s, 60 s, ... up to 30 min between attempts
        if any(k in reason for k in ("gap_stop", "rugged", "liquidity_pull", "dev_dump", "max_trade_loss")):
            def _ban(m=m, creator=p.get("creator"), sym=p.get("sym"), reason=reason):   # background: the Jupiter lookup used to hold the sell lock up to 60 s on the exits where seconds matter
                try: j = scam.jup(m); scam.ban(creator, j.get("dev")); log.warning("[solana] BLACKLIST creator of %s (%s)", sym, reason)
                except Exception: pass
            import threading; threading.Thread(target=_ban, daemon=True).start()
        q = s.quote(m, USDC, raw, s.c["slippage_bps"])
        if not q:
            p["noroute"] = p.get("noroute", 0)+1; log.warning("[solana] sell %s: no route (%d)", p["sym"], p["noroute"])
            if p["noroute"] < 10 or frac < 1: return
        got = int(q["outAmount"])/1e6 if q else 0.0; fee = s.net_fee_usd(); cost = p["cost"]*raw/p["raw"]
        if s.live:
            r_ = s.sell_live(m, reason, raw)
            if not r_:
                p["sellfail"] = p.get("sellfail", 0)+1; p.setdefault("fail_t", time.time()); p["fail_last"] = time.time()
                if not s.writeoff_due(m, p, frac): return
                log.warning("[solana] WRITE-OFF %s: %d failed sells / %d no-route over %.0f min and pool liquidity gone -> booked as total loss, slot freed, mint excluded from re-adoption", p["sym"], p["sellfail"], p.get("noroute", 0), (time.time()-p["fail_t"])/60)
                got, sig = 0.0, "writeoff"; reason = f"{reason} WRITEOFF"; s.__dict__.setdefault("dead", {})[m] = time.time()
            else:
                got, sig = r_; reason = f"{reason} REAL tx={sig}"
                import live_sol; fs_ = live_sol.tx_fee_sol(sig) if sig != "late_landing" else None; fee = fs_*s.sol if fs_ else fee   # no RPC lookup for the synthetic signature (used to stall ~30 s inside the sell lock)
        rent = p.get("rent_usd", 0) if frac >= 1 else 0
        pnl = got-fee-cost-rent; s.cash += got-fee; s.trades.append(pnl)
        if rent: reason += f" rent={rent:.2f}"
        if pnl < 0:   # post-mortem 30/10: re-entries after a loss = 31 closes, -1.04 USD -> longer cooldown only after losing closes
            e_ = s.seen.setdefault(m, {"t": time.time()}); e_["cool"] = max(e_.get("cool", 0), time.time()+s.c.get("loss_cooldown_hours", 2)*3600)
        if frac >= 1:
            s.pos.pop(m)
            if s.live: s.__dict__.setdefault("_ata_q", {})[m] = {"t": time.time(), "n": 0}   # rent recovery: close the empty token account (ata_sweep)
        else: p["raw"] -= raw; p["cost"] -= cost; p["realized"] = p.get("realized", 0)+pnl
        if s.live: s.reconcile()
        try: s.save()
        except Exception: pass
        s.record(p["sym"], "SELL", got/(raw/10**p["dec"]) if raw else 0, raw/10**p["dec"], fee, pnl, f"meme:{reason}" + (f" ({frac:.0%})" if frac < 1 else ""))
    def writeoff_due(s, m, p, frac=1.0):
        """A live position is written off only when ALL hold: full-size sell, >= writeoff_sellfail failed swaps, >= 10 no-route quotes,
        >= writeoff_min_s since the first failure, AND DexScreener still lists the pair with liquidity below writeoff_max_liq_usd.
        A pure Jupiter/RPC outage never writes anything off: with no pair data the answer is False."""
        c = s.c
        if frac < 1 or p.get("sellfail", 0) < c.get("writeoff_sellfail", 5) or p.get("noroute", 0) < 10: return False
        if time.time()-p.get("fail_t", time.time()) < c.get("writeoff_min_s", 900): return False
        pr = (getattr(s, "_rd_last", None) or {}).get(m)
        liq = (pr or {}).get("liquidity", {}).get("usd") if isinstance((pr or {}).get("liquidity"), dict) else None
        if liq is None: return False                          # no pair or no liquidity figure (DexScreener data gap) is not evidence of a dead pool
        if s.quote(USDC, SOL, 1_000_000) is None: return False  # Jupiter itself is down: the failed sells prove nothing
        return float(liq) < c.get("writeoff_max_liq_usd", 1000)
    def buy_live(s, m, p, sc, why, size):
        import jupr
        with jupr.prio(1): return s._buy_live(m, p, sc, why, size)
    def _buy_live(s, m, p, sc, why, size):
        import live_sol
        if os.path.exists("KILL_solana"): log.warning("[solana] KILL_solana present: no buys"); return
        liq = (p.get("liquidity") or {}).get("usd") or 0; lam = int(size/max(s.sol, 1)*1e9)
        try:
            q0 = live_sol.quote(live_sol.SOL, m, lam, 100)
            slip = live_sol.slippage_bps(size, liq, float(q0.get("priceImpactPct") or 0)*100)
            if slip > s.c.get("max_buy_slip_bps", 400): log.warning("[solana] LIVE buy %s blocked: needs %d bps slippage tolerance > max_buy_slip_bps", p["baseToken"]["symbol"], slip); return
            q = live_sol.quote(live_sol.SOL, m, lam, slip)
            ok, txt = live_sol.sellable(m, int(q["outAmount"]), slip, s.c["max_roundtrip_loss_pct"], lam)   # expected fill, NOT otherAmountThreshold (= outAmount x (1-slip)): the floor inflated rt by >= 1% and the EV>=3x gate blocked every live buy (31-oct)
            if not ok: log.warning("[solana] LIVE buy %s blocked: not sellable (%s)", p["baseToken"]["symbol"], txt); return
            imp_ = float(q.get("priceImpactPct") or 0)*100; rt_ = float(txt.split("=")[1].rstrip("%")); ev_ = p.get("_ev")
            if imp_ > 1.0: log.warning("[solana] LIVE buy %s blocked: impact %.2f%% > 1%% (100bps)", p["baseToken"]["symbol"], imp_); return
            if ev_ is None or ev_ < 3*max(rt_, 0): log.warning("[solana] LIVE buy %s blocked: EV %s%% < 3x real round-trip %.2f%%", p["baseToken"]["symbol"], ev_, rt_); return
            before = live_sol.token_balances().get(m, (0, p.get("_dec") or 6))[0]
            sig = live_sol.swap(q)
        except Exception as e: log.warning("[solana] LIVE buy %s failed: %s", p["baseToken"]["symbol"], e); return
        time.sleep(3)
        try: tb = live_sol.token_balances(); raw, dec = tb.get(m, (int(q["outAmount"]), p.get("_dec") or 6)); qty = raw-before
        except Exception: qty, dec = int(q["outAmount"]), p.get("_dec") or 6
        if qty <= 0: qty = int(q["outAmount"])
        fs = live_sol.tx_fee_sol(sig); fee = fs*s.sol if fs else s.net_fee_usd(); px = size/(qty/10**dec); sym = p["baseToken"]["symbol"]
        s.pos[m] = dict(sym=sym, raw=qty, dec=dec, entry=px, best=px, cost=size+fee, t=time.time(), impact=float(q.get("priceImpactPct") or 0)*100, score=sc, pair=p.get("url"), sig=sig, slip=slip, liq_buy=liq)
        if before == 0: s.pos[m]["rent_usd"] = ATA_RENT_SOL*s.sol   # token-account rent (0.00203928 SOL, not in meta.fee): booked in the realised PnL at the full exit, NOT in the cost the -6% hard stop is measured from (it would fire on every $3-5 buy)
        sq = s.quote(m, USDC, qty, s.c["slippage_bps"]); x0 = int(sq["outAmount"])/1e6/(qty/10**dec) if sq else px*0.97
        rt = (1-x0/px)*100; P = s.pos[m]
        P.update(mark0=x0, best=x0, rt=rt, stop_pct=max(s.c["stop_pct"], min(s.c["max_stop_pct"], s.c["stop_pct"]+rt/100)), pair_addr=p.get("pairAddress"),
                 liq0=liq, creator=(s.seen.get(m, {}).get("rc") or {}).get("creator"), cbal0=(s.seen.get(m, {}).get("rc") or {}).get("creator_bal", 0), partial=False)
        s.reconcile(); s.post_buy(m, p, P, px, rt, sc, f"{why} REAL tx={sig} slip={slip}bps", fee, qty, dec, sym)
    def sell_live(s, m, reason, raw):
        import live_sol
        p = s.pos[m]; urgent = any(k in reason for k in ("kill", "rug", "liquidity_pull", "dev_dump", "gap", "max_trade_loss", "stop"))
        val = p.get("mark", p["entry"])*raw/10**p["dec"]; sol0 = live_sol.sol_balance()
        try: bal0 = live_sol.token_balances().get(m, (p["raw"],))[0]
        except Exception: bal0 = p["raw"]
        for attempt in range(3):
            try:
                slip = live_sol.slippage_bps(val, p.get("liq_buy") or p.get("liq0") or 50000, p.get("impact", 0), urgent)*(1+attempt*0.5)
                q = live_sol.quote(m, live_sol.SOL, raw, min(2500, slip)); sig = live_sol.swap(q, urgent=urgent); break   # urgent exits pay a higher priority fee (live_sol.prio_for)
            except Exception as e:
                log.warning("[solana] LIVE sell %s attempt %d failed: %s", p["sym"], attempt+1, e); time.sleep(3)
                try:
                    if live_sol.token_balances().get(m, (0,))[0] <= max(0, bal0-raw*0.99):   # sell landed late (or 6024: no tokens) -> treat as filled; bal0 makes this correct for partial sells (33%/50%) too
                        got_sol = max(0.0, live_sol.sol_balance()-sol0); log.warning("[solana] LIVE sell %s: tokens already gone -> filled (late landing)", p["sym"])
                        return (got_sol*s.sol if got_sol > 0 else val), "late_landing"
                except Exception: pass
        else: return None
        time.sleep(3); got_sol = max(0.0, live_sol.sol_balance()-sol0)
        if got_sol <= 0: got_sol = int(q["outAmount"])/1e9
        return got_sol*s.sol, sig
    def record(s, sym, side, px, qty, fee, pnl, reason):
        row = [dt.datetime.now().isoformat(timespec="seconds"), EX, sym, side, f"{px:.6g}", f"{qty:.6g}", f"{fee:.4f}", f"{pnl:.4f}", reason, f"{s.equity():.2f}"]
        with open(s.csv, "a", newline="") as f: csv.writer(f).writerow(row)
        if "PUMP-PLAY" in reason or "pump_exit" in reason or getattr(s, "_pump_sell", False):
            pf = f"trades_{EX}_pump.csv"; new = not os.path.exists(pf)
            with open(pf, "a", newline="") as f:
                w = csv.writer(f)
                if new: w.writerow("time,exchange,symbol,side,price,qty,fee,pnl,reason,equity,mode".split(","))
                w.writerow(row + ["live" if s.live else "paper"])
        log.info("TRADE %s", " | ".join(row))
    # ---------------- Risk ----------------
    def marks(s):
        if not s.pos: return {}
        out = {}
        if s.live:
            out = {k: v["mark"] for k, v in s.pos.items() if v.get("mark") and time.time()-v.get("mark_t", 0) < 40}
            if len(out) == len(s.pos): return out
        for m, p in s.pos.items():
            if m in out: continue
            q = s.quote(m, USDC, p["raw"], s.c["slippage_bps"])     # mark = executable exit value (includes impact)
            if q: out[m] = int(q["outAmount"])/1e6/(p["raw"]/10**p["dec"])
            time.sleep(0.3)
        return out
    def risk_data(s):
        """per-position on-chain/market risk: liquidity, 5m sell pressure (DexScreener), dev balance (RugCheck, every 5 min)"""
        if not s.pos: return {}
        out = {}
        prs = get("https://api.dexscreener.com/tokens/v1/solana/" + ",".join(s.pos)) or []
        for pr in prs:
            m = pr["baseToken"]["address"]
            if m in s.pos and pr.get("pairAddress") == s.pos[m].get("pair_addr", pr.get("pairAddress")): out[m] = pr
        for m in s.pos:
            if m not in out:
                cand = [pr for pr in prs if pr["baseToken"]["address"] == m]
                if cand: out[m] = max(cand, key=lambda x: (x.get("liquidity") or {}).get("usd", 0))
        return out
    def manage(s, mk, rd=None):
        c = s.c; rd = rd or {}
        for m in list(s.pos):
            p = s.pos.get(m); x = mk.get(m)
            if not p: continue
            if x is None:
                p["noroute_mark"] = p.get("noroute_mark", 0)+1
                if p["noroute_mark"] > 20: s.sell(m, "no_route")
                continue
            p["noroute_mark"] = 0; base = p.get("mark0", p["entry"])
            p["best"] = max(p["best"], x); p["mark"] = x; r = x/base-1; rb = p["best"]/base-1
            pr = rd.get(m); why = None
            if pr:
                liq = (pr.get("liquidity") or {}).get("usd") or 0; t5 = (pr.get("txns") or {}).get("m5") or {}
                b5, s5 = t5.get("buys", 0), t5.get("sells", 0)
                if p.get("liq0") and liq < p["liq0"]*(1-c["liq_pull_pct"]): why = f"liquidity_pull {liq:.0f}<{p['liq0']:.0f}"
                elif c.get("exit_mode") == "trail" and s5 >= c["sell_spike_min_tx"] and s5 > c["sell_spike_ratio"]*max(1, b5):
                    nv = x*p["raw"]/10**p["dec"]/p["cost"]-1
                    if nv > 0 and x > p["best"]*(1-c.get("trail_pct_tt", 12)/100): why = f"whale_spike_lock {s5}s/{b5}b net={nv*100:+.1f}%"
                elif s5 >= c["sell_spike_min_tx"] and s5 > c["sell_spike_ratio"]*max(1, b5) and time.time()-p["t"] >= c.get("pump_grace_s", 75): why = f"sell_pressure {s5}s/{b5}b"
            if not why and p.get("creator") and time.time()-p.get("dev_t", 0) > 300:
                p["dev_t"] = time.time(); full = get(f"https://api.rugcheck.xyz/v1/tokens/{m}/report")
                if full and p.get("cbal0", 0) > 0 and (full.get("creatorBalance") or 0) < p["cbal0"]*0.5: why = "dev_dump"
                if full and full.get("rugged"): why = "rugged"
            grace_ = s.live and time.time()-p["t"] < c.get("pump_grace_s", 75)
            if not why and p.get("play") == "pump" and not grace_:
                I_ = s.insider_feat(m); fl_ = set((getattr(s, "smart", {}).get(m) or {}).get("flags") or []); A_ = getattr(s, "ai_scores", {}).get(m, {})
                if I_["sells"] >= 1: why = "pump_exit:insider_sell"
                elif fl_ & {"dev_selling", "whale_dump"}: why = "pump_exit:" + ",".join(sorted(fl_ & {"dev_selling", "early_exit", "whale_dump"}))
                elif "early_exit" in fl_ and (p.get("gnet") if p.get("gnet") is not None else -1) >= 0: why = "pump_exit:early_exit"   # alone: only if net >= 0 (coins recovered after 6/10 early exits)
                elif A_.get("sig_exh"): why = f"pump_exit:exhaustion exh={A_.get('exh')}"
                elif time.time()-p["t"] > c.get("pump_max_hold_min", 45)*60: why = "pump_exit:time"
                if why and why != "pump_exit:time":
                    p["pexit_n"] = p.get("pexit_n", 0)+1
                    if p["pexit_n"] < 2: log.info("[solana] %s %s (1/2, waiting for confirmation)", p["sym"], why); why = None
                else: p["pexit_n"] = 0
            if not why and (base-x)*p["raw"]/10**p["dec"] > s.equity()*p.get("mtl", c.get("max_trade_loss_pct", 0.015)): why = "max_trade_loss"
            if not why:
                I = s.insider_feat(m); sm_ = getattr(s, "smart", {}).get(m, {}); fl = list(sm_.get("flags") or [])
                if I["sells"] >= 3: fl.append("insider_sell")
                if fl and fl != p.get("ins_flags"):
                    p["ins_flags"] = fl; log.info("[solana] EXIT-INTEL %s %s (%s)", p.get("sym"), fl, "LIVE-paper" if s.promo().get("exit") else "sombra")
                    open("research/exit_intel.jsonl", "a").write(json.dumps(dict(ts=time.time(), mint=m, sym=p.get("sym"), flags=fl, px=x, r=r))+"\n")
                bad = [f for f in fl if f in ("insider_sell", "dev_selling", "early_exit", "whale_dump")]
                if bad and s.promo().get("exit") and not grace_: why = "exit_intel:" + ",".join(bad)
            if why: s.sell(m, why); continue
            if c.get("exit_mode") == "trail" and p.get("play") != "pump":
                why = trail_exit(x, p, c)
                if why: s.sell(m, why)
                continue
            stop = p.get("stop_pct", c["stop_pct"])
            if not p.get("partial") and r >= p.get("tp_pct", c["partial_tp_pct"]):
                s.sell(m, f"partial_tp +{r*100:.0f}%", c["partial_tp_frac"]); p = s.pos.get(m)
                if p: p["partial"] = True; p["stop_pct"] = -0.0   # runner: stop moved to break-even
                continue
            if r <= -stop:
                if stop > 0 and r < -2*stop: log.warning("[solana] GAP LOSS %s r=%.1f%% vs stop %.1f%% (rug/gap; bounded by max_gap_loss_pct)", p.get("sym"), r*100, stop*100)
                s.sell(m, ("gap_stop" if r < -2*stop else "stop") if stop > 0 else "breakeven")
            elif rb >= p.get("act_pct", c["trail_activate_pct"]) and x <= p["best"]*(1-(p.get("runner_pct", c["runner_trail_pct"]) if p.get("partial") else p.get("trail_w", c["trail_pct"]))): s.sell(m, "trail")
            elif time.time()-p["t"] > c["max_hold_hours"]*3600: s.sell(m, "time_exit")
    def risk_audit(s):
        """startup: close stablecoin impersonators, trim positions above the gap cap"""
        cap = s.equity()*s.c.get("max_gap_loss_pct", 0.03)
        for m, p in list(s.pos.items()):
            v = p.get("mark", p["entry"])*p["raw"]/10**p["dec"]
            if stable_fake(p.get("sym", ""), p.get("mark")): log.warning("[solana] AUDIT close %s: stablecoin impersonator", p.get("sym")); s.sell(m, "audit_stable_impersonator")
            elif v > cap*1.1: log.warning("[solana] AUDIT trim %s value=%.2f cap=%.2f", p.get("sym"), v, cap); s.sell(m, "audit_trim_to_cap", 1-cap/v)
    def robust_equity(s, rd=None):
        """for the daily stop: per position median of (guard mark, DexScreener price, Jupiter price v3); ignore failed/zero; None if no data at all"""
        import statistics as st_
        rd = rd if rd is not None else (getattr(s, "_rd_last", None) or {})
        jp = {}   # DexScreener + guard mark only (Jupiter calls saved)
        tot = s.cash
        for m, p in s.pos.items():
            v = [x for x in (p.get("mark"), float((rd.get(m) or {}).get("priceUsd") or 0), float(((jp or {}).get(m) or {}).get("usdPrice") or 0)) if x and x > 0]
            if not v: return None
            tot += st_.median(v)*p["raw"]/10**p["dec"]
        return tot
    def equity(s): return s.cash + sum(p.get("mark", p["entry"])*p["raw"]/10**p["dec"] for p in s.pos.values())
    # ---------------- control/status ----------------
    def control(s):
        f = f"control_{EX}.json"
        try: ctl = json.load(open(f)) if os.path.exists(f) else {}
        except Exception: ctl = {}
        s.paused = bool(ctl.get("pause"))
        if ctl.get("close"):
            for sym in ctl["close"]:
                for m, p in list(s.pos.items()):
                    if sym in (m, p["sym"]): s.sell(m, "manual_close")
            ctl["close"] = []; json.dump(ctl, open(f+".tmp", "w")); os.replace(f+".tmp", f)
    def ins_st(s):
        if time.time()-getattr(s, "_ins_t", 0) > 30:
            s._ins_t = time.time()
            try: s._ins = json.load(open("insider_status.json")) if time.time()-os.path.getmtime("insider_status.json") < 900 else {}
            except Exception: s._ins = {}
        return s._ins
    def promo(s):
        try: return json.load(open("insider_promoted.json"))
        except Exception: return {}
    def insider_feat(s, m):
        st = s.ins_st(); c = (st.get("conv") or {}).get(m, {})
        T = (st.get("tokens") or {}).get(m, {}); V = st.get("tok_valid") or {}
        return dict(conv=c.get("score", 0), n=c.get("n", 0), elite=c.get("elite", 0), sells=(st.get("sells_by_mint") or {}).get(m, 0),
                    tok=T.get("score", 0), w=float(V.get("weight") or 0), whale_net=T.get("whale_net"), dev_sell=T.get("dev_sell"))
    def guard_loop(s):
        """profit protection: live positions marked every ~guard_s; locks net profit on volatile / reversing coins, partial on spikes"""
        import statistics as st_
        c = s.c; G = c.get("guard_s", 12); rdt = 0; rd = {}
        while True:
            time.sleep(G)
            c = s.c   # hot reload of guard parameters (config.json is edited while the bot runs)
            if not s.live or not s.pos: continue
            try:
                rd = s.risk_data() or {}; rdt = time.time(); s._rd_last = rd   # DexScreener: 1 batched call per cycle; on failure fall through to Jupiter quotes instead of re-stamping stale prices
                for m in list(s.pos):
                    p = s.pos.get(m)
                    if not p: continue
                    qty = p["raw"]/10**p["dec"]; dpx = float((rd.get(m) or {}).get("priceUsd") or 0)
                    if dpx > 0: x = dpx*(1-max(0.0, p.get("rt", 1.0))/200)            # exit value ~ DexScreener price minus half the round-trip cost
                    else:
                        q = s.quote(m, USDC, p["raw"], c["slippage_bps"])
                        if not q: continue
                        x = int(q["outAmount"])/1e6/qty
                    val = x*qty; p["mark"] = x; p["mark_t"] = time.time(); p["best"] = max(p.get("best", x), x)
                    age = time.time()-p["t"]; grace = age < c.get("pump_grace_s", 75)
                    net = (val - s.net_fee_usd() - p["cost"])/p["cost"]
                    h = p.setdefault("ghist", []); h.append([time.time(), x]); del h[:-80]
                    rets = [h[i][1]/h[i-1][1]-1 for i in range(1, len(h))]
                    rv_now = st_.pstdev(rets[-10:]) if len(rets) >= 10 else 0; rv_old = st_.pstdev(rets[-30:-10]) if len(rets) >= 30 else rv_now
                    atr = float((p.get("lv") or {}).get("atr_pct") or 0)
                    volatile = atr >= c.get("guard_atr_hi", 2.0) or (rv_old > 0 and rv_now > 1.5*rv_old) or rv_now*100 >= 1.0
                    # reversal / exhaustion
                    rev = []
                    I = s.insider_feat(m); fl = set((getattr(s, "smart", {}).get(m) or {}).get("flags") or []); A = getattr(s, "ai_scores", {}).get(m, {})
                    if A.get("sig_exh"): rev.append("exhaustion")
                    if I["sells"] >= 1 or I.get("dev_sell"): rev.append("insider_dev_sell")
                    if fl & {"dev_selling", "early_exit", "whale_dump"}: rev.append("smart_flags")
                    pr = rd.get(m) or {}; v = pr.get("volume") or {}
                    if v.get("h1") and (v.get("m5") or 0) < 0.4*v["h1"]/12: rev.append("volume_fade")
                    px = [y for _, y in h[-40:]]
                    pk = [px[i] for i in range(1, len(px)-1) if px[i] >= px[i-1] and px[i] > px[i+1]]
                    if len(pk) >= 2 and pk[-1] < pk[-2] and px[-1] < pk[-1]: rev.append("lower_high")
                    p["rev_n"] = (p.get("rev_n", 0)+1) if rev else 0
                    if p["rev_n"] < 2: rev = []                     # reversal/volume-fade needs 2 consecutive confirmations
                    thr = min(c.get("guard_thr_max", 0.04), max(c.get("guard_thr_min", 0.02), 1.5*atr/100))
                    p["gnet"] = round(net*100, 2); p["gthr"] = round(thr*100, 2)
                    why = None; frac = 1.0
                    j_ = x/h[-3][1]-1 if len(h) >= 3 else 0
                    if j_ >= c.get("spike_exit_pct", 0.08) and net > 0:   # whale spike: big jump in 1-2 checks + volume burst -> full exit
                        pr2 = (s.risk_data() or {}).get(m) or pr; v2 = pr2.get("volume") or {}; lq = (pr2.get("liquidity") or {}).get("usd") or 1
                        burst = (v2.get("m5") or 0) >= max(2*(v2.get("h1") or 0)/12, 0.03*lq)
                        if burst: why = f"spike_exit +{j_*100:.1f}%/{2*G}s vol5m={v2.get('m5', 0):.0f} liq={lq:.0f} net={net*100:.1f}%"
                    if why: pass
                    elif grace: pass                                # grace period: only spike_exit (here) and hard stop / rug / dev dump (manage)
                    elif p.get("glock") is not None and net <= p["glock"]: why = f"protect_lock net={net*100:.1f}%<=lock {p['glock']*100:.1f}%"
                    elif net >= thr and rev: why = f"protect_take net={net*100:.1f}% ({','.join(rev)})"
                    elif net >= thr and volatile:
                        lock = max(p.get("glock") or -1, c.get("guard_lock_min", 0.008), net - max(thr, 2*rv_now))
                        if lock != p.get("glock"): log.info("[solana] GUARD %s lock net>=%.1f%% (net %.1f%%, atr %.2f%%, rv %.2f%%)", p["sym"], lock*100, net*100, atr, rv_now*100)
                        p["glock"] = lock
                    if not why and not grace and not p.get("gspike") and net >= thr:
                        old = [y for t, y in h if time.time()-t >= 55]
                        if old and x/old[-1]-1 >= c.get("guard_spike_pct", 0.06): why = f"protect_spike +{(x/old[-1]-1)*100:.1f}%/1m"; frac = c.get("guard_spike_frac", 0.33)
                    if why:
                        log.warning("[solana] GUARD %s %s", p["sym"], why); s.sell(m, why, frac)
                        if frac < 1 and m in s.pos: s.pos[m]["gspike"] = True; s.pos[m]["glock"] = max(s.pos[m].get("glock") or -1, c.get("guard_lock_min", 0.008))
                if time.time()-getattr(s, "_glog", 0) > 120:
                    s._glog = time.time(); log.info("[solana] GUARD " + " | ".join(f"{p['sym']} net={p.get('gnet')}% thr={p.get('gthr')}% lock={None if p.get('glock') is None else round(p['glock']*100,2)}" for p in s.pos.values()))
            except Exception as e: log.warning("[solana] guard %s", e)
    def smart_loop(s):
        """SHADOW smart-money: re-profile wallets every 2h; every ~2 min signals for held tokens + recent passed candidates"""
        import smart_money as sm
        prof_t = os.path.getmtime(sm.F_W) if os.path.exists(sm.F_W) else 0
        while True:
            try:
                if time.time()-prof_t > 7200:
                    best = {}
                    for l in open(f"candidates_{EX}.jsonl").readlines()[-20000:]:
                        try: r = json.loads(l)
                        except Exception: continue
                        if r.get("pair") and (r.get("liq") or 0) >= 20000: best[r["pair"]] = r
                    sm.profile(list(best)[-120:]); prof_t = time.time()
                W = sm.load(); targets = {}
                for m, p in list(s.pos.items()):
                    if p.get("pair_addr") or p.get("pair"): targets[m] = (p.get("pair_addr") or p.get("pair"), p.get("sym"), p.get("t"), True)
                recent = []
                for l in open(f"candidates_{EX}.jsonl").readlines()[-400:]:
                    try: recent.append(json.loads(l))
                    except Exception: pass
                for r in reversed(recent):
                    if r.get("pass") and r.get("pair") and r["mint"] not in targets and len(targets) < 8: targets[r["mint"]] = (r["pair"], r.get("sym"), None, False)
                for m, (pair, sym, et, held) in targets.items():
                    try: dev = scam.jup(m).get("dev")
                    except Exception: dev = None
                    g = sm.signals(pair, dev, et, W, s.c.get("whale_usd", 3000))
                    flags = [k for k, ok in (("smart_buy", g["smart_buyers"] >= 2), ("dev_selling", g["dev_sell_usd"] > 0), ("early_exit", g["early_n"] and g["early_sellers"] >= max(3, g["early_n"]*0.3)),
                                             ("whale_dump", g["whale_net_usd"] < -10000), ("whale_accum", g["whale_net_usd"] > 10000)) if ok]
                    rec = dict(ts=time.time(), mint=m, sym=sym, held=held, flags=flags, **g); s.smart[m] = rec; sm.shadow_log(rec)
                    if flags: log.info("[solana] SMART (shadow) %s %s %s", sym, ",".join(flags), {k: g[k] for k in ("smart_buyers", "early_sellers", "dev_sell_usd", "whale_net_usd")})
                s.smart = {k: v for k, v in s.smart.items() if time.time()-v["ts"] < 1800}
            except Exception as e: log.warning("smart_loop %s", e)
            time.sleep(120)
    def ai_loop(s):
        """shadow: AI pump / exhaustion scores from live 1m bars + DexScreener flows (research/pump_study.py: not validated -> no trading effect)"""
        import ai_pump, news
        while True:
            try:
                now = time.time(); s.ai_watch = {k: v for k, v in s.ai_watch.items() if now-v["t"] < 3600}
                todo = [(m, v["pair"], v, False) for m, v in s.ai_watch.items() if now-s.ai_scores.get(m, {}).get("at", 0) > 180]
                todo += [(m, P.get("pair_addr"), {"sym": P["sym"], "src": "", "dx": {}}, True) for m, P in s.pos.items() if now-s.ai_scores.get(m, {}).get("at", 0) > 120 and P.get("pair_addr")]
                ns = news.state(); heads = " ".join(n["title"].lower() for n in ns.get("top", []))
                narr = [w for w, _ in (s.brain.ctx.get("narratives") or [])] if isinstance(s.brain.ctx.get("narratives"), list) and s.brain.ctx.get("narratives") and isinstance(s.brain.ctx["narratives"][0], (list, tuple)) else (s.brain.ctx.get("narratives") or [])
                ai_heat = any(str(w).lower() in ("ai", "agent", "gpt", "bot", "agi") for w in narr) or len(s.ai_watch) >= 5
                for m, pair, v, held in sorted(todo, key=lambda x: not x[3])[:6]:
                    d = get(f"https://api.geckoterminal.com/api/v2/networks/solana/pools/{pair}/ohlcv/minute", aggregate=1, limit=200, currency="usd")
                    try: bars = sorted(x[:6] for x in d["data"]["attributes"]["ohlcv_list"])
                    except Exception: time.sleep(2.2); continue
                    if len(bars) < 30: time.sleep(2.2); continue
                    sc = ai_pump.scores(bars, v.get("dx"), trending="trending" in str(v.get("src")), news_hits=heads.count(v["sym"].lower()) if len(v["sym"]) > 2 else 0,
                                        ai_heat=ai_heat, G=s.c.get("ai_pump_params"))
                    s.ai_scores[m] = dict(at=time.time(), sym=v["sym"], held=held, pump=sc["pump"], exh=sc["exh"], sig_pump=sc["sig_pump"], sig_exh=sc["sig_exh"],
                                          pump_parts=sc["pump_parts"], exh_parts=sc["exh_parts"], price=sc["f"]["c"])
                    open("pump_solana.jsonl", "a").write(json.dumps({"t": dt.datetime.now().isoformat(timespec="seconds"), "mint": m, **s.ai_scores[m], "f": sc["f"]}) + "\n")
                    if sc["sig_pump"] or sc["sig_exh"]: log.info("[solana] AI-SHADOW %s pump=%d exh=%d sig_pump=%s sig_exh=%s%s", v["sym"], sc["pump"], sc["exh"], sc["sig_pump"], sc["sig_exh"], " (en cartera)" if held else "")
                    time.sleep(2.2)
            except Exception as e: log.info("[solana] ai_loop: %s", e)
            time.sleep(30)
    def status(s):
        eq = s.equity(); t = s.trades
        pos = [{"sym": p["sym"], "side": "LONG", "strategy": f"meme s{p['score']}" + (" ½TP" if p.get("partial") else ""), "entry": p["entry"], "mark": p.get("mark", p["entry"]),
                "stop": p.get("mark0", p["entry"])*(1-p.get("stop_pct", s.c["stop_pct"])), "trailing": p["best"]/p.get("mark0", p["entry"])-1 >= p.get("act_pct", s.c["trail_activate_pct"]), "tp": p.get("mark0", p["entry"])*(1+p.get("tp_pct", s.c["partial_tp_pct"])), "lv": p.get("lv"), "pump": s.ai_scores.get(m, {}).get("pump"), "exh": s.ai_scores.get(m, {}).get("exh"), "cost": p["cost"],
                "pnl": p.get("mark", p["entry"])*p["raw"]/10**p["dec"]-p["cost"]+p.get("realized", 0), "pnl_pct": (p.get("mark", p["entry"])/p["entry"]-1)*100,
                "age_min": (time.time()-p["t"])/60, "mint": m} for m, p in s.pos.items()]
        st = {"exchange": EX, "mode": "live" if s.live else "paper", "ts": time.time(), "equity": eq, "cash": s.cash, "day_pnl_pct": (eq/s.day_start-1)*100 if s.day_start else 0,
              "halted": s.halted or (s.live and os.path.exists("KILL_solana")), "paused": s.paused, "wallet": getattr(s, "wallet", None), "live_min_sol": s.c.get("live_min_sol", 0.05), "pump_play": s.pump_stats(), "regime": {"regime": "memecoins", "sol_usd": round(s.sol, 2)}, "fng": None, "headlines": [], "delist": [], "listings": [],
              "universe": len(s.cands), "positions": pos, "pending": [], "signals": s.signals[-60:], "movers": s.cands[:15],
              "smart": {"wallets": len(__import__("smart_money").load()), "items": sorted(getattr(s, "smart", {}).values(), key=lambda r: (-len(r["flags"]), -r["ts"]))[:15]},
              "ai_pump": sorted([{k: v[k] for k in ("sym", "pump", "exh", "sig_pump", "sig_exh", "held", "pump_parts", "exh_parts")} | {"age_s": round(time.time()-v["at"])} for v in s.ai_scores.values() if time.time()-v["at"] < 900], key=lambda x: -x["pump"])[:12],
              "eval": s.eval_summary(), "brain": {"model": {k: s.brain.st.get(k) for k in ("updated", "n_labelled", "active", "oos", "base", "avg_win", "avg_loss", "weights")},
              "ctx": {k: v for k, v in s.brain.ctx.items() if k not in ("heat_hist", "words")}, "decisions": s.decisions[:25]}, "stats": {"closed_trades": len(t), "closed": len(t), "win_rate": (sum(1 for x in t if x > 0)/len(t)) if t else None, "net_pnl": sum(t)}}
        json.dump(st, open(f"status_{EX}.json.tmp", "w"), default=str); os.replace(f"status_{EX}.json.tmp", f"status_{EX}.json")
        if time.time()-s.eq_t >= 30:
            s.eq_t = time.time()
            with open(f"equity_{EX}.csv", "a") as f: f.write(f"{int(time.time())},{eq:.4f}\n")
    # ---------------- main step ----------------
    def step(s):
        s.reload(); c = s.c; s.control()
        if dt.date.today().isoformat() != s.day: s.day, s.halted, s.day_start = dt.date.today().isoformat(), False, s.equity()
        sp = get("https://lite-api.jup.ag/price/v3", ids=SOL) or {}; s.sol = float((sp.get(SOL) or {}).get("usdPrice") or s.sol)
        s.sol24 = float((sp.get(SOL) or {}).get("priceChange24h") or s.sol24)
        if s.sol > 0: s.wallet_check()
        if s.live and os.path.exists("KILL_solana") and (s.pos or not s.halted):
            s.halted = True; log.warning("[solana] KILL_solana file: closing REAL positions, no new buys"); [s.sell(m, "kill_switch_file") for m in list(s.pos)]
        if s.live:
            s.reconcile()
            if not s.halted and not getattr(s, "_halt_chk", False):
                s._halt_chk = True
                try:
                    if not (os.path.exists('halt_override.json') and json.load(open('halt_override.json')).get('day') == s.day) and any(r_[0].startswith(s.day) and "kill_switch" in r_[8] for r_ in csv.reader(open(s.csv)) if len(r_) > 8):
                        s.halted = True; s.save(); log.warning("[solana] daily stop already hit today (kill_switch in CSV): halted restored, closing positions")
                        [s.sell(m_, "kill_switch_restore") for m_ in list(s.pos)]
                except Exception as e: log.warning("halt restore %s", e)
        if s.live and os.path.exists("unhalt_once.json"):     # one-shot: undo the restore-halt that fired by mistake at 19:01 (override already approved today)
            try:
                if json.load(open("unhalt_once.json")).get("day") == s.day: s.halted = False; s._stop_n = 0; log.warning("[solana] unhalt_once applied (day_start kept %.2f)", s.day_start); s.save()
            except Exception as e: log.warning("unhalt_once %s", e)
            os.remove("unhalt_once.json")
        if s.live and os.path.exists("halt_override.json"):   # user-approved override: clear halt, re-baseline day at real wallet equity
            try:
                o = json.load(open("halt_override.json"))
                if o.get("day") == s.day and not o.get("applied"):
                    s.reconcile(); s.halted = False; s._halt_chk = True; s.day_start = s.robust_equity() or s.equity()
                    o.update(applied=time.time(), new_day_start=s.day_start); json.dump(o, open("halt_override.json", "w")); s.save()
                    log.warning("[solana] HALT OVERRIDE by user: halted cleared, day_start=%.2f", s.day_start)
                if o.get("day") == s.day: s._halt_chk = True
            except Exception as e: log.warning("override %s", e)
        rd_ = s.risk_data(); s._rd_last = rd_
        s.manage(s.marks(), rd_); s.ata_sweep()
        eq_ = s.robust_equity(rd_) if s.live else s.equity()
        br_ = s.day_start > 0 and eq_ is not None and eq_/s.day_start-1 <= -c["daily_max_drawdown_pct"]
        s._stop_n = (getattr(s, "_stop_n", 0)+1) if br_ else 0
        if br_: log.warning("[solana] daily stop check: robust equity %.2f vs base %.2f (%d/2)", eq_, s.day_start, s._stop_n)
        if s._stop_n >= (2 if s.live else 1) and not s.halted:
            s.halted = True; s.save(); log.warning("[solana] KILL SWITCH"); [s.sell(m, "kill_switch") for m in list(s.pos)]
        elif s.halted and s.pos and not os.path.exists("KILL_solana"):   # halted == flatten: a deferred / failed / no-route sell is retried every step (back-off in _sell0) until the book is flat; lifting the halt (override, unhalt_once, new day) stops it
            [s.sell(m, "kill_switch") for m in list(s.pos)]
        if time.time()-s.scan_t >= c["scan_seconds"]:
            s.scan_t = time.time(); s.scan_cycle()
        if time.time()-getattr(s, "ev_t", 0) > 1800:
            s.ev_t = time.time()
            import threading, eval_solana
            def _ev(c=dict(s.c)):
                try: eval_solana.run(c); log.info("[solana] forward-eval updated")
                except Exception as e: log.warning("eval fail %s", e)
            threading.Thread(target=_ev, daemon=True).start()
        if time.time()-s.learn_t > 3600:
            s.learn_t = time.time(); import threading
            def _learn(c=dict(s.c)):
                try: s.brain.learn(c)
                except Exception: log.exception("[brain] learn failed")   # a daemon thread that dies silently every hour looks like a frozen model
                try: s.director_cycle()
                except Exception: log.exception("[director] cycle failed")
            threading.Thread(target=_learn, daemon=True).start()
        log.info("[solana] equity=%.2f cash=%.2f open=%s SOL=%.2f", s.equity(), s.cash, [p["sym"] for p in s.pos.values()], s.sol)
        s.status()
    def _cache_io(s, save):
        import pickle; fn = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state", "sol_caches.pkl")
        try:
            if save:
                os.makedirs(os.path.dirname(fn), exist_ok=True); tmp = fn+".tmp"
                pickle.dump({"ttl": {k: v for k, v in getattr(s, "_ttl", {}).items() if time.time()-v[0] < 1800}, "bars": {k: v for k, v in getattr(s, "_bars", {}).items() if time.time()-v[0] < 300}}, open(tmp, "wb")); os.replace(tmp, fn)
            elif os.path.exists(fn):
                d = pickle.load(open(fn, "rb")); s.__dict__.setdefault("_ttl", {}).update(d.get("ttl", {})); s.__dict__.setdefault("_bars", {}).update(d.get("bars", {}))
                log.info("[solana] caches restored: %d ttl, %d bars", len(d.get("ttl", {})), len(d.get("bars", {})))
        except Exception as e: log.info("[solana] cache io %s", e)
    def prefetch_rug(s, need, budget_s=150, workers=4):
        """Fetch rug reports for `need` in parallel inside a wall-clock budget. Success -> s._rc[m]; failure or past the
        budget -> s._rc_fail[m] (fail-closed: the candidate is vetoed as rugcheck_unavailable this cycle). Returns (fetched, past_budget)."""
        from concurrent.futures import ThreadPoolExecutor, wait
        if not need: return 0, 0
        ex_ = ThreadPoolExecutor(workers); futs = {ex_.submit(s.rug, m): m for m in need}
        pending = set(futs); deadline = time.time()+max(1, budget_s); fetched = 0
        while pending and time.time() < deadline:
            done, pending = wait(pending, timeout=min(30, max(0.5, deadline-time.time())))
            for fut in done:
                m = futs[fut]
                try: r_ = fut.result()
                except Exception as e: log.warning("rug %s %s", m, e); r_ = None
                if r_: s._rc[m] = (time.time(), r_); fetched += 1
                else: s._rc_fail[m] = time.time()
            im = getattr(s, "inline_manage", None)
            if im: im()                                       # stops / rug exits must not wait up to budget_s for RugCheck
        for fut in pending: s._rc_fail[futs[fut]] = time.time()
        ex_.shutdown(wait=False, cancel_futures=True)
        if pending: log.warning("[solana] rugcheck budget %ss hit: %d reports not fetched this cycle", budget_s, len(pending))
        return fetched, len(pending)
    HARD_PERM = {"mint_authority", "freeze_authority", "dev_rug_history", "transfer_tax"}   # cannot change within the hour
    HARD_SLOW = {"lp_unlocked", "few_holders"}                                             # can change (LP burned later, holders growing): short skip only
    def inline_manage(s):
        """keep managing open positions while a long scan step runs (at most every 30 s)"""
        if not s.pos or time.time()-getattr(s, "_imt", 0) < 30: return
        s._imt = time.time()
        try: s.manage({k: v["mark"] for k, v in s.pos.items() if v.get("mark")} if s.live else s.marks())
        except Exception as e: log.warning("inline manage %s", e)
    def stamp_hardfail(s, m, fails, rc, c):
        """remember a deterministic veto so the eval slots go to mints that can still pass; never from the GoPlus fallback (its LP/holders data is partial)"""
        if (rc or {}).get("src") == "goplus+rpc": return
        HF = s.__dict__.setdefault("_hardfail", {}); F = set(fails)
        if s.HARD_PERM & F: HF[m] = (time.time(), c.get("hardfail_skip_s", 3600))
        elif s.HARD_SLOW & F: HF[m] = (time.time(), c.get("hardfail_short_s", 900))
    def eval_slots(s, ok_, mints, c):
        """Spend the max_eval_per_cycle slots on mints that can still pass: a mint stamped by stamp_hardfail less than its TTL ago is
        skipped (open positions and insider-sourced mints are always evaluated). Returns (keep set, skipped list)."""
        HF = s.__dict__.setdefault("_hardfail", {}); now = time.time()
        for k in [k for k, v in HF.items() if now-v[0] >= v[1]]: HF.pop(k, None)
        skipped = [m for m in ok_ if m not in s.pos and mints.get(m) != "insider" and m in HF]
        sk = set(skipped)
        return set([m for m in ok_ if m not in sk][:c.get("max_eval_per_cycle", 60)]), skipped
    def scan_cycle(s):
        if not getattr(s, "_cache_loaded", False): s._cache_loaded = True; s._cache_io(False)
        try: return s._scan_cycle()
        finally: s._cache_io(True)
    def _scan_cycle(s):
        c = s.c; mints = s.scan(); prs = s.pairs(mints); cands = []
        try: btc_on = json.load(open("status_binance.json")).get("regime", {}).get("regime") != "bear"
        except Exception: btc_on = None
        ctx = s.brain.update_context(s.gctx + [{"name": p["baseToken"].get("name", ""), "sym": p["baseToken"]["symbol"]} for p in prs.values()], s.sol24, btc_on)
        pb = ctx["playbook"]
        import news; ns = news.state(); nb = ns.get("coin_block", {}); nbo = ns.get("coin_boost", {})
        mt = time.time(); t0_ = time.time()
        # cheap prefilter from list data, then parallel RugCheck prefetch (cache TTL 10 min); vetoes unchanged
        ok_ = [m for m, p in prs.items() if ((p.get("liquidity") or {}).get("usd") or 0) >= c["min_liquidity_usd"] and ((p.get("volume") or {}).get("h1") or 0) >= c.get("pre_min_vol_h1", 2000)]
        ok_.sort(key=lambda m: -(((prs[m].get("volume") or {}).get("h1") or 0) + (1e9 if m in s.pos or mints[m] == "insider" else 0)))
        keep, skipped_hf = s.eval_slots(ok_, mints, c)
        if not hasattr(s, "_rc"): s._rc, s._rc_fail = {}, {}
        # negative cache: a mint RugCheck/GoPlus could not report is not re-fetched for rc_fail_cache_s (veto unchanged: still rugcheck_unavailable)
        need = [m for m in keep if time.time()-s._rc.get(m, (0, None))[0] > 600 and time.time()-s._rc_fail.get(m, 0) > c.get("rc_fail_cache_s", 180)]
        fetched, timed_out = s.prefetch_rug(need, budget_s=c.get("rc_scan_budget_s", 150))
        log.info("[solana] prefilter %d/%d -> eval %d (%d skipped: hard-vetoed <%ds ago), rugcheck fetched %d/%d (%d past budget) in %.0fs", len(ok_), len(prs), len(keep), len(skipped_hf), c.get("hardfail_skip_s", 3600), fetched, len(need), timed_out, time.time()-t0_)
        for m, p in prs.items():
            if m not in keep:
                if ((p.get("liquidity") or {}).get("usd") or 0) < c["min_liquidity_usd"]: s.logc({"ts": dt.datetime.now().isoformat(timespec="seconds"), "mint": m, "sym": p["baseToken"]["symbol"], "src": mints[m], "liq": round((p.get("liquidity") or {}).get("usd") or 0), "pass": False, "fail": ["liq"]})
                elif m in skipped_hf: s.logc({"ts": dt.datetime.now().isoformat(timespec="seconds"), "mint": m, "sym": p["baseToken"]["symbol"], "src": mints[m], "liq": round((p.get("liquidity") or {}).get("usd") or 0), "pass": False, "fail": ["hardfail_recent"]})
                continue
            s.inline_manage()                            # keep managing open positions while scanning
            liq = (p.get("liquidity") or {}).get("usd") or 0
            rec = {"ts": dt.datetime.now().isoformat(timespec="seconds"), "mint": m, "sym": p["baseToken"]["symbol"], "src": mints[m], "dex": p.get("dexId"),
                   "price": p.get("priceUsd"), "pair": p.get("pairAddress"), "liq": round(liq), "mcap": p.get("marketCap") or p.get("fdv"), "pass": False, "fail": []}
            if liq < c["min_liquidity_usd"]: rec["fail"].append("liq"); s.logc(rec); continue
            if stable_fake(rec["sym"], p.get("priceUsd")): rec["fail"].append("stable_impersonator"); s.logc(rec); continue
            last = s.seen.get(m, {})
            rc = (s._rc.get(m) or (0, None))[1] or (None if m in s._rc_fail else s.rug(m))
            if not rc: rec["fail"].append("rugcheck_unavailable"); s.logc(rec); continue
            rec["rug"] = rc; f = rec["fail"]
            if rc["mint_auth"]: f.append("mint_authority")
            if rc["freeze_auth"]: f.append("freeze_authority")
            if rc["top10"] > c["max_top10_pct"]: f.append("top10")
            if rc["lp_locked"] < c["min_lp_locked_pct"]: f.append("lp_unlocked")
            if rc["rugged"] or rc["creator_rugs"]: f.append("dev_rug_history")
            if rc["fee_pct"] > 0: f.append("transfer_tax")
            if rc.get("score_norm") is None: f.append("rc_score_missing")   # fail-closed: a report without a score must not read as score 0
            elif rc["score_norm"] > c.get("max_rc_norm", 20): f.append(f"rc_score{rc['score_norm']}")   # data 31-oct: >20 -> 57% dead vs 20%
            if (rc.get("holders") or 0) < c.get("min_holders", 5000): f.append("few_holders")   # data 31-oct: <5000 -> 76% dead vs 2%
            if "USD" in rec["sym"].upper() and 0.5 < float(p.get("priceUsd") or 0) < 1.5: f.append("stablecoin")
            if rc["danger"]: f.append("rugcheck_danger:" + "|".join(rc["danger"][:3]))
            s.stamp_hardfail(m, f, rc, c)   # deterministic veto: no point re-fetching RugCheck for it for a while
            sc, comp = s.score(p, rc, m); rec["score"], rec["parts"] = sc, comp
            I = s.insider_feat(m); rec["insider"] = I
            # insider v3: per-token score weighted by its rolling out-of-sample hit rate (weight 0 until validated); scam filters keep veto via f
            # owner order: insider TOP priority -> token score (-15..15) x3 x weight (0.7 = up to +-31 of 100 score points)
            adj = I["w"]*3*max(-15, min(15, I["tok"]))
            if s.promo().get("convergence") and I["conv"] >= 3: adj = max(adj, min(12, 3*I["conv"]))
            if adj: rec["score"] = sc = round(max(0, min(100, sc + adj)), 1); rec["insider_adj"] = round(adj, 1)
            SOFT = ("top10",)
            pp0 = rec.get("parts") or {}
            if not [x for x in f if x not in SOFT] and (pp0.get("m5") or 0) <= 0 and I["elite"] < 3:
                f.append("no_momentum_m5")      # both the normal entry and pump-play need m5>0: skip the 2 Jupiter quotes (fail-closed)
            rec["roundtrip_loss_pct"] = None
            pp = rec.get("parts") or {}
            if not f and c.get("require_momentum") and not ((pp.get("m5") or 0) > 0 and (pp.get("h1") or 0) > 0): f.append("no_momentum")
            rec["narr"] = s.brain.narrative(p["baseToken"].get("name", ""), rec["sym"]); rec["heat"] = ctx["heat"]
            try:
                import ai_pump
                if liq >= c["min_liquidity_usd"] and ai_pump.is_ai(p["baseToken"].get("name", ""), rec["sym"], (p.get("info") or {}).get("description", ""), narr=rec["narr"]):
                    rec["ai"] = True; s.ai_watch[m] = dict(pair=p.get("pairAddress"), sym=rec["sym"], name=p["baseToken"].get("name", ""), src=rec["src"], dx=p, t=time.time())
            except Exception as e: log.debug("ai detect %s", e)
            dec = s.brain.decide(rec, s.equity(), c); rec["brain"] = dec
            thr = c["min_score"] + pb["score_adj"] + (c.get("news_riskoff_score_add", 10) if ns.get("risk_off") else 0) - (5 if nbo.get(rec["sym"].upper(), 0) > time.time() else 0)
            if nb.get(rec["sym"].upper(), 0) > time.time() and not f: f.append("news_negative")
            # manipulated-pump play: coordinated accumulation but provably sellable; only soft (concentration/score) failures allowed
            setup = [k for k, ok in (("rug_insiders", rc["insiders"] >= 1), ("concentrated", rc["top10"] > c["max_top10_pct"]), ("insider_accum", I["conv"] >= 3),
                                     ("whales", (comp.get("whale_buys") or 0) >= 2), ("bundled_bots", (comp.get("bot_wallets") or 0) >= 3)) if ok]
            hard = [x for x in f if x not in SOFT]
            pp = rec.get("parts") or {}
            elite0 = I["elite"] >= 3 and I["sells"] < 3 and I["w"] >= 0.45
            final = not hard and (sc >= thr or elite0 or (dec and dec["active"]) or (setup and (c.get("pump_play", False) or c.get("pump_paper")) and (pp.get("m5") or 0) > 0))
            if final and m not in s.pos and len(s.pos) < c["max_positions"] and not s.halted:   # sellability quote only for final buy candidates (fail-closed)
                rt, q = s.honeypot(m, 100)
                rec["roundtrip_loss_pct"] = round(rt, 2) if rt is not None else None
                if rt is None: f.append(q)
                elif rt > c["max_roundtrip_loss_pct"]: f.append("honeypot/high_tax")
            elif not hard: f.append("no_sellability_check")
            hard = [x for x in f if x not in SOFT]
            pump_ok = ((c.get("pump_play", False) or c.get("pump_paper")) and setup and not hard and not rc["mint_auth"] and not rc["freeze_auth"] and rc["lp_locked"] >= c["min_lp_locked_pct"]
                       and (rc.get("fee_pct") or 0) == 0 and rec.get("roundtrip_loss_pct") is not None and rec["roundtrip_loss_pct"] <= c.get("pump_max_rt_pct", 4)
                       and (pp.get("m5") or 0) > 0 and I["sells"] == 0 and rc["top10"] <= c.get("pump_max_top10_pct", 45))
            elite_trig = I["elite"] >= 3 and I["sells"] < 3 and I["w"] >= 0.45      # 3+ elite wallets bought it <30 min ago
            if elite_trig and not f: rec["pass"] = True; rec["trigger"] = "insider_elite_group"; log.warning("[solana] INSIDER TRIGGER %s elite=%d conv=%d tok=%s (filters passed)", rec["sym"], I["elite"], I["conv"], I["tok"])
            elif dec and dec["active"]: rec["pass"] = not f and dec.get("ev_ok", dec["ev_pct"] > 0) and sc >= c.get("brain_min_score", 45)
            else: rec["pass"] = not f and sc >= thr
            if pump_ok and not rec["pass"] and not c.get("pump_play", False):   # PAPER-ONLY pump-play: never reaches s.buy
                try:
                    sf_ = scam.check(m, rec["sym"], p.get("priceUsd"), c, rec.get("roundtrip_loss_pct"))
                    if not sf_: s.pump_paper_open(m, rec, p, setup)
                    else: log.info("[solana] PUMP-PAPER scam block %s: %s", rec["sym"], ",".join(sf_))
                except Exception as e: log.warning("pump paper %s", e)
                pump_ok = False; f.append("pump_paper_only")
            if pump_ok and not rec["pass"]: rec["pass"] = True; rec["trigger"] = "pump_play"; rec["setup"] = setup; f.clear(); log.warning("[solana] PUMP-PLAY candidate %s setup=%s top10=%s rt=%s", rec["sym"], setup, rc["top10"], rec.get("roundtrip_loss_pct"))
            if rec["pass"] and I["w"]*I["tok"] <= -3 and rec.get("trigger") != "insider_elite_group": rec["pass"] = False; f.append("insider_negative")
            if not f and not rec["pass"]: f.append(f"brain_ev<=0" if dec and dec["active"] else f"score<{thr}")
            if dec: s.decisions = ([{"t": now_s(), "sym": rec["sym"], "score": sc, **{k: dec[k] for k in ("p", "ev_pct", "kelly_pct", "size")}, "pass": rec["pass"], "fail": ",".join(f) or "OK", "narr": ",".join(rec["narr"])}] + s.decisions)[:40]
            s.seen[m] = {"t": time.time() if "rc" not in last or time.time()-last.get("t", 0) > 600 else last["t"], "rc": rc, "holders": rc["holders"] if "holders" not in last or time.time()-last.get("t", 0) > 600 else last["holders"],
                         "liq": liq if "liq" not in last or time.time()-last.get("t", 0) > 600 else last["liq"], "top10": rc["top10"] if "top10" not in last or time.time()-last.get("t", 0) > 600 else last["top10"],
                         "watch": time.time()+1800 if sc >= c["min_score"]-15 and not [x for x in f if not x.startswith("score")] else last.get("watch", 0), "cool": last.get("cool", 0)}
            if rec["pass"] and m not in s.pos:   # Director gate (plays / hourly window / daily cap): only ever tightens; logged as director_gate (not a veto for the dataset)
                okd, whyd = director.entry_allowed(c, dt.datetime.now().hour, s.buys_today(), "pump" if rec.get("trigger") == "pump_play" else "insider_elite" if rec.get("trigger") == "insider_elite_group" else "scanner")
                if not okd: rec["pass"] = False; f.append("director_gate"); rec["director"] = whyd; log.info("[solana] %s: %s", rec["sym"], whyd)
            if rec["pass"] and m not in s.pos and not s.halted and not s.paused and len(s.pos) < c["max_positions"] and s.seen.get(m, {}).get("cool", 0) < time.time():   # scam vetoes BEFORE the single log line (a later block used to log the same mint twice: pass=True then pass=False -> polluted eval/brain data)
                try: sf0 = scam.check(m, rec["sym"], p.get("priceUsd"), c, rec.get("roundtrip_loss_pct"))
                except Exception as e: sf0 = ["scam_error"]; log.warning("scam check %s", e)
                if sf0: log.info("[solana] SCAM block %s: %s", rec["sym"], ",".join(sf0)); rec["pass"] = False; f.extend(x for x in sf0 if x not in f); rec["scam"] = sf0
            s.logc(rec); cands.append(rec)
            s.signals.append({"t": now_s(), "sym": rec["sym"], "type": "meme-scan", "strategy": "meme" if rec["pass"] else "-", "side": 1 if rec["pass"] else 0,
                              "chg5": comp.get("m5"), "vol": comp.get("vol_liq"), "rsi": sc, "mtf": ",".join(f) or "OK", "rs": comp.get("h1")})
            if rec["pass"] and m not in s.pos and not s.halted and not s.paused and len(s.pos) < c["max_positions"] and s.seen[m].get("cool", 0) < time.time():
                size = (dec["size"] if dec and dec["active"] else s.equity()*(c.get("max_position_pct", 0.08) if c.get("exit_mode") == "volscale" else c["position_pct"])*pb["size_mult"]) * (0.5 if ns.get("risk_off") else 1.0)
                C_ = s.__dict__.setdefault("_ttl", {}); dc_ = C_.get(("depth", m))
                if dc_ and time.time()-dc_[0] < 600: curve, cap = dc_[1]
                else: curve, cap = s.brain.depth_curve(s.quote, m, USDC); C_[("depth", m)] = (time.time(), (curve, cap)); rec["depth"] = curve
                if c.get("exit_mode") == "trail" and not (dec and dec["active"]): size = s.equity()*c.get("size_pct", 8)/100
                size = min(size, cap, s.cash*0.98)
                if rec.get("trigger") == "pump_play": size *= c.get("pump_size_frac", 0.3); p["_play"] = "pump"
                else: p["_play"] = None
                mn = c.get("live_min_trade_usd", 1) if s.live else 10
                if s.live:   # live target $3-5: scales with score and insider signal
                    I_ = s.insider_feat(m); q_ = min(1.0, max(0.0, (sc-c["min_score"])/20 + max(0, I_["tok"])/15*I_["w"]))
                    mn = max(mn, c.get("live_target_min_usd", 3) + (c.get("live_target_max_usd", 5)-c.get("live_target_min_usd", 3))*q_)
                    lim = min(s.equity()*c.get("max_gap_loss_pct", 0.1), s.cash*0.98, cap, s.equity()*c.get("max_trade_loss_pct", 0.015)/c.get("max_stop_pct", 0.15))
                    if mn > lim: mn = max(c.get("live_min_trade_usd", 1), lim)
                if s.live and size < mn and mn <= s.equity()*c.get("max_gap_loss_pct", 0.1) and mn <= s.cash*0.98 and cap >= mn \
                        and mn*c.get("max_stop_pct", 0.15) <= s.equity()*c.get("max_trade_loss_pct", 0.015):
                    log.info("[solana] %s size %.2f sized to $%.2f target (within %.0f%% cap and risk budget)", rec["sym"], size, mn, c.get("max_gap_loss_pct", 0.1)*100); size = mn
                p["_floor"] = mn if s.live else 0
                if size < mn: log.info("[solana] %s skipped: size %.1f (depth cap %s)", rec["sym"], size, cap); continue
                p["_riskoff"], p["_btc_on"], p["_smult"] = bool(ns.get("risk_off")), btc_on, pb["size_mult"]
                p["_ev"] = dec["ev_pct"] if dec and dec["active"] else None   # rugpull 31-oct: live needs EV >= 3x measured round-trip
                p["_dec"] = rc["dec"]; p["_size"] = size; p["_slip"] = int(min(300, max(50, 2*100*max(curve.values() or [1.0]))))
                try: sf = scam.check(m, rec["sym"], p.get("priceUsd"), c, rec.get("roundtrip_loss_pct"))
                except Exception as e: sf = ["scam_error"]; log.warning("scam check %s", e)   # fail-closed: an exception in the scam layer is not a pass
                if sf: log.info("[solana] SCAM block %s: %s", rec["sym"], ",".join(sf)); rec["fail"] = sf; s.logc(rec); continue
                s.buy(m, p, sc, f"liq={liq:.0f} top10={rc['top10']}% lp={rc['lp_locked']}% rt={rec.get('roundtrip_loss_pct')}%")
                s.seen[m]["cool"] = time.time()+c["reentry_cooldown_hours"]*3600
        s.signals = s.signals[-200:]
        s.cands = sorted(({"sym": r["sym"], "chg5": r.get("score")} for r in cands), key=lambda x: -(x["chg5"] or 0))
        s.seen = {k: v for k, v in s.seen.items() if time.time()-v.get("t", 0) < 3*86400 or k in s.pos}
        log.info("[solana] SCAN %d mints, %d pairs, %d >= liq, %d passed all filters", len(mints), len(prs), len(cands), sum(r["pass"] for r in cands))
    def pump_paper_open(s, m, rec, p, setup):
        """paper-only pump-play ledger (trades_solana_pump_paper.csv); zero real-money effect"""
        import threading
        P = s.__dict__.setdefault("_pp_open", {})
        if m in P or len(P) >= 5: return
        px = float(p.get("priceUsd") or 0)
        if px <= 0: return
        P[m] = dict(sym=rec["sym"], entry=px, best=px, t=time.time(), rt=float(rec.get("roundtrip_loss_pct") or 0), setup=",".join(setup))
        log.warning("[solana] PUMP-PAPER OPEN %s px=%.8g rt=%s%% setup=%s", rec["sym"], px, rec.get("roundtrip_loss_pct"), setup)
        if not getattr(s, "_pp_thr", None):
            s._pp_thr = threading.Thread(target=s._pump_paper_loop, daemon=True); s._pp_thr.start()
    def _pump_paper_loop(s):
        import requests
        while True:
            time.sleep(15)
            try:
                P = s.__dict__.get("_pp_open", {})
                if not P: continue
                c = s.c; r = requests.get("https://api.dexscreener.com/tokens/v1/solana/" + ",".join(P), timeout=10).json()
                px = {}
                for q in r if isinstance(r, list) else []:
                    mt = (q.get("baseToken") or {}).get("address")
                    if mt in P and float(q.get("priceUsd") or 0) > 0 and float((q.get("liquidity") or {}).get("usd") or 0) > px.get(mt, (0, 0))[1]:
                        px[mt] = (float(q["priceUsd"]), float((q.get("liquidity") or {}).get("usd") or 0))
                for mt, v in list(P.items()):
                    age = time.time()-v["t"]; why = None
                    if mt not in px:
                        if age > 300: why, cur = "pump_paper:no_price(rug?)", v["entry"]*0.0
                        else: continue
                    else:
                        cur, liq = px[mt]; v["best"] = max(v["best"], cur); g = cur/v["entry"]-1
                        if liq < 5000: why = "pump_paper:liq_pulled"
                        elif g <= -c.get("pump_stop_pct", 0.06): why = "pump_paper:stop"
                        elif g >= c.get("pump_tp_pct", 0.15): why = "pump_paper:tp"
                        elif v["best"]/v["entry"]-1 >= c.get("pump_trail_act", 0.04) and cur <= v["best"]*(1-c.get("pump_trail_pct", 0.05)): why = "pump_paper:trail"
                        elif age > c.get("pump_max_hold_min", 25)*60: why = "pump_paper:time"
                    if not why: continue
                    gross = cur/v["entry"]-1
                    cost = v["rt"]/100 + c.get("pump_paper_extra_slip_pct", 1.0)/100   # measured Jupiter round-trip + extra slippage
                    net = gross - cost
                    pf = f"trades_{EX}_pump_paper.csv"; new = not os.path.exists(pf)
                    with open(pf, "a") as fh:
                        if new: fh.write("t_open,t_close,sym,mint,entry,exit,gross_pct,cost_pct,net_pct,hold_min,reason,setup,tag\n")
                        fh.write(f"{dt.datetime.fromtimestamp(v['t']).isoformat(timespec='seconds')},{dt.datetime.now().isoformat(timespec='seconds')},{v['sym']},{mt},{v['entry']:.10g},{cur:.10g},{gross*100:.2f},{cost*100:.2f},{net*100:.2f},{age/60:.1f},{why},{v['setup'].replace(',', '|')},PUMP_PAPER\n")
                    log.warning("[solana] PUMP-PAPER CLOSE %s net=%.2f%% %s", v["sym"], net*100, why); P.pop(mt, None)
            except Exception as e: log.warning("pump paper loop %s", e)
    def pump_stats(s):
        try:
            rows = list(csv.DictReader(open(f"trades_{EX}_pump.csv"))); sells = [float(r["pnl"]) for r in rows if r["side"] == "SELL"]
            return dict(trades=len(sells), pnl=round(sum(sells), 4), wins=sum(x > 0 for x in sells), open=[p["sym"] for p in s.pos.values() if p.get("play") == "pump"])
        except Exception: return dict(trades=0, pnl=0, wins=0, open=[p["sym"] for p in s.pos.values() if p.get("play") == "pump"])
    def eval_summary(s):
        try: return json.load(open("eval_solana.json"))
        except Exception: return None
    def logc(s, rec):
        with open(f"candidates_{EX}.jsonl", "a") as f: f.write(json.dumps(rec, default=str)+"\n")
    def run(s):
        try: s.risk_audit()
        except Exception as e: log.warning('risk_audit %s', e)
        s.ai_watch, s.ai_scores = {}, {}; import threading as _th; _th.Thread(target=s.ai_loop, daemon=True).start()
        s.smart = {}; _th.Thread(target=s.smart_loop, daemon=True).start(); _th.Thread(target=s.guard_loop, daemon=True).start()
        if s.c.get("exit_mode") == "volscale":                      # retro-fit per-coin levels to positions opened before
            for mm, P in list(s.pos.items()):
                if (P.get("lv") or {}).get("mode") == "volscale": continue
                try:
                    if not P.get("pair_addr"):
                        dd = get("https://api.dexscreener.com/tokens/v1/solana/" + mm) or []
                        if dd: P["pair_addr"] = max(dd, key=lambda q: (q.get("liquidity") or {}).get("usd") or 0)["pairAddress"]
                    lv = s.coin_levels(P.get("pair_addr"), P.get("mark0", P["entry"]), P.get("rt", 2.5)); s.apply_levels(P, lv)
                    open("levels_solana.jsonl", "a").write(json.dumps({"t": now_s(), "sym": P["sym"], "entry": P["entry"], "retrofit": True, **lv}) + "\n")
                    log.info("[solana] levels %s retrofit: atr=%.2f%% volx=%.2f stop=%.1f%% tp=%.1f%% trail=%.1f%%@%.1f%%", P["sym"], lv["atr_pct"], lv["vol_mult"], P["stop_pct"]*100, P["tp_pct"]*100, P["trail_w"]*100, P["act_pct"]*100)
                except Exception as e: log.info("[solana] levels retrofit %s: %s", P.get("sym"), e)
                time.sleep(2.2)
            s.save()
        while not os.path.exists(f"STOP_{EX}") and not os.path.exists("STOP"):
            try: s.step(); s.save()
            except Exception as e: log.exception("step error %s", e)
            for _ in range(int(s.c["poll_seconds"])):
                if os.path.exists(f"STOP_{EX}") or os.path.exists("STOP"): break
                time.sleep(1)
        s.save(); log.info("[solana] stopped")
def main(cfg, live):
    if live and not (os.environ.get("SOLANA_PRIVATE_KEY") and os.environ.get("LIVE_CONFIRM") == "YES"):
        sys.exit("Live refused: needs SOLANA_PRIVATE_KEY and LIVE_CONFIRM=YES")
    import news; news.start(120)
    Meme(cfg, live).run()
