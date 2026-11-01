"""Exchange adapters. Each adapter: market data (public) + live broker. Add a new exchange = new class + register in ADAPTERS."""
import os, time, hmac, hashlib, json, uuid, re, logging, secrets
from urllib.parse import urlencode
import requests, numpy as np, pandas as pd
log = logging.getLogger("bot")
STABLE = {"USDC","USDT","FDUSD","TUSD","BUSD","DAI","USDP","EUR","EURI","AEUR","USDE","PYUSD","XUSD","USD1","BFUSD","RLUSD","TRY","BRL",
          "GBP","PAXG","XAUT","WBTC","WBETH","BNSOL","U","USDS","EURC","GUSD","CBETH","LSETH","MSOL","USDG","GYEN"}
def lev(b): return any(b.endswith(t) for t in ("UP","DOWN","BULL","BEAR"))

class Exchange:
    name = "base"; quote = "USDT"; btc = "BTCUSDT"
    def __init__(s, cfg): s.cfg = cfg; s.sess = requests.Session(); s.sess.headers["User-Agent"] = "Mozilla/5.0"; s.filters = {}
    def base_of(s, sym): return sym[:-len(s.quote)]
    # to implement: universe(min_vol) -> list ; books() -> {sym: (bid, ask)} ; klines(sym, tf, n) -> df[t,o,h,l,c,v,tb] closed only
    #               depth(sym, n) -> (bids, asks) [[p,q]] ; live_buy/live_sell

class Binance(Exchange):
    name, quote, btc = "binance", "USDT", "BTCUSDT"
    HOSTS = ["https://api.binance.com", "https://data-api.binance.vision", "https://api1.binance.com"]
    host = None
    def get(s, path, **p):
        for h in ([s.host] if s.host else []) + s.HOSTS:
            try:
                r = s.sess.get(h + path, params=p, timeout=10)
                if r.status_code == 200: s.host = h; return r.json()
            except requests.RequestException: pass
        raise RuntimeError("binance unreachable " + path)
    def universe(s, min_vol):
        info = s.get("/api/v3/exchangeInfo", permissions="SPOT")
        listed = {x["symbol"]: x for x in info["symbols"] if x["status"] == "TRADING" and x["quoteAsset"] == s.quote}
        try:
            prods = s.sess.get("https://www.binance.com/bapi/asset/v2/public/asset-service/product/get-products", timeout=10).json()["data"]
            non = {p["s"] for p in prods if any(re.search(r"stock|commod|stable|fiat|etf", t or "", re.I) for t in (p.get("tags") or []))}
        except Exception: non = {k for k, x in listed.items() if x["baseAsset"].endswith("B") and len(x["baseAsset"]) > 3}
        vol = {t["symbol"]: float(t["quoteVolume"]) for t in s.get("/api/v3/ticker/24hr", type="MINI")}
        out = [k for k, x in listed.items() if k not in non and x["baseAsset"] not in STABLE and not lev(x["baseAsset"]) and vol.get(k, 0) >= min_vol]
        for k in out:
            f = {x["filterType"]: x for x in listed[k]["filters"]}; st = float(f["LOT_SIZE"]["stepSize"]); tk = float(f["PRICE_FILTER"]["tickSize"])
            s.filters[k] = {"step": st, "tick": tk}
        return sorted(out, key=lambda k: -vol[k])
    def books(s):
        s._bk = {b["symbol"]: (float(b["bidPrice"]), float(b["askPrice"])) for b in s.get("/api/v3/ticker/bookTicker")}; return s._bk
    def book(s, sym): return s._bk[sym]
    def klines(s, sym, tf, n=200):
        k = s.get("/api/v3/klines", symbol=sym, interval=tf, limit=n)
        df = pd.DataFrame(k).iloc[:, [0,1,2,3,4,5,9]].astype(float); df.columns = ["t","o","h","l","c","v","tb"]
        return df.iloc[:-1].reset_index(drop=True)
    def depth(s, sym, n=20):
        ob = s.get("/api/v3/depth", symbol=sym, limit=n); return ob["bids"], ob["asks"]
    # ---- live (signed) ----
    def _signed(s, method, path, **p):
        k, sec = os.environ["BINANCE_API_KEY"], os.environ["BINANCE_API_SECRET"].encode()
        p["timestamp"] = int(time.time()*1000); q = urlencode(p); q += "&signature=" + hmac.new(sec, q.encode(), hashlib.sha256).hexdigest()
        r = requests.request(method, "https://api.binance.com" + path + "?" + q, headers={"X-MBX-APIKEY": k}, timeout=10); r.raise_for_status(); return r.json()
    def _fmt(s, x, step): d = max(0, -int(np.floor(np.log10(step)))); return f"{np.floor(x/step)*step:.{d}f}"
    def live_order(s, sym, side, qty=None, quote_amt=None, limit_px=None, maker=False):
        f = s.filters[sym]
        if maker and limit_px:   # LIMIT_MAKER = post-only (rejected if it would take) -> maker fee
            qty = qty or quote_amt/limit_px
            o = s._signed("POST", "/api/v3/order", symbol=sym, side=side, type="LIMIT_MAKER", quantity=s._fmt(qty, f["step"]), price=s._fmt(limit_px, f["tick"]))
        elif side == "BUY" and quote_amt: o = s._signed("POST", "/api/v3/order", symbol=sym, side="BUY", type="MARKET", quoteOrderQty=f"{quote_amt:.2f}")
        else: o = s._signed("POST", "/api/v3/order", symbol=sym, side=side, type="MARKET", quantity=s._fmt(qty*0.999, f["step"]))
        return o
    def live_order_status(s, sym, oid): return s._signed("GET", "/api/v3/order", symbol=sym, orderId=oid)
    def live_cancel(s, sym, oid): return s._signed("DELETE", "/api/v3/order", symbol=sym, orderId=oid)

class Coinbase(Exchange):
    """Coinbase Advanced Trade. Public: /api/v3/brokerage/market/*. Live: CDP API key (COINBASE_API_KEY = key name, COINBASE_API_SECRET = EC PEM) -> JWT ES256."""
    name, quote, btc = "coinbase", "USD", "BTC-USD"
    API = "https://api.coinbase.com/api/v3/brokerage"
    GR = {"1m": "ONE_MINUTE", "5m": "FIVE_MINUTE", "15m": "FIFTEEN_MINUTE", "1h": "ONE_HOUR", "4h": "SIX_HOUR"}
    SEC = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 21600}
    def base_of(s, sym): return sym.split("-")[0]
    def get(s, path, **p):
        for _ in range(3):
            try:
                r = s.sess.get(s.API + path, params=p, timeout=10)
                if r.status_code == 200: return r.json()
                if r.status_code == 429: time.sleep(1)
            except requests.RequestException: time.sleep(1)
        raise RuntimeError("coinbase unreachable " + path)
    def _products(s):
        s._prod = s.get("/market/products", product_type="SPOT", limit=1000)["products"]; s._prod_t = time.time(); return s._prod
    def universe(s, min_vol):
        out = []
        for p in s._products():
            b = p["base_display_symbol"]
            if p["quote_currency_id"] != s.quote or p["status"] != "online" or p["trading_disabled"] or p.get("cancel_only") or p.get("view_only"): continue
            if b in STABLE or lev(b): continue
            v = float(p.get("approximate_quote_24h_volume") or 0)
            if v >= min_vol: out.append((v, p["product_id"])); s.filters[p["product_id"]] = {"step": float(p["base_increment"]), "tick": float(p["quote_increment"])}
        return [k for _, k in sorted(out, reverse=True)]
    def books(s):
        """Bulk: last price for all products (1 call). Exact bid/ask per symbol via book()."""
        out = {}
        for p in s._products():
            try:
                px = float(p.get("price") or 0)
                if px > 0: out[p["product_id"]] = (px, px)
            except ValueError: pass
        return out
    def book(s, sym):
        t = s.sess.get(f"https://api.exchange.coinbase.com/products/{sym}/ticker", timeout=10).json()
        return float(t["bid"]), float(t["ask"])
    def klines(s, sym, tf, n=200):
        n = min(n, 349); end = int(time.time()); start = end - s.SEC[tf]*(n+1)
        k = s.get(f"/market/products/{sym}/candles", granularity=s.GR[tf], start=str(start), end=str(end), limit=n+1)["candles"]
        df = pd.DataFrame(k)[["start","open","high","low","close","volume"]].astype(float); df.columns = ["t","o","h","l","c","v"]
        df["t"] *= 1000; df = df.sort_values("t").reset_index(drop=True); df["tb"] = df.v*0.5   # no taker-buy split on Coinbase
        return df.iloc[:-1].reset_index(drop=True)
    def depth(s, sym, n=20):
        pb = s.get("/market/product_book", product_id=sym, limit=n)["pricebook"]
        return [[x["price"], x["size"]] for x in pb["bids"]], [[x["price"], x["size"]] for x in pb["asks"]]
    # ---- live ----
    def _jwt(s, method, path):
        import jwt
        from cryptography.hazmat.primitives import serialization
        name, pem = os.environ["COINBASE_API_KEY"], os.environ["COINBASE_API_SECRET"].replace("\\n", "\n")
        if "BEGIN" in pem: key, alg = serialization.load_pem_private_key(pem.encode(), password=None), "ES256"
        else:                                                   # new CDP keys: base64 Ed25519 (seed+pub, 64 bytes)
            import base64; from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
            key, alg = Ed25519PrivateKey.from_private_bytes(base64.b64decode(pem.strip())[:32]), "EdDSA"
        uri = f"{method} api.coinbase.com/api/v3/brokerage{path.split('?')[0]}"
        return jwt.encode({"sub": name, "iss": "cdp", "nbf": int(time.time()), "exp": int(time.time())+120, "uri": uri},
                          key, algorithm=alg, headers={"kid": name, "nonce": secrets.token_hex()})
    def _req(s, method, path, body=None):
        r = requests.request(method, s.API + path, json=body, headers={"Authorization": "Bearer " + s._jwt(method, path)}, timeout=10)
        r.raise_for_status(); return r.json()
    def _fmt(s, x, step): d = max(0, -int(np.floor(np.log10(step)))); return f"{np.floor(x/step)*step:.{d}f}"
    def live_order(s, sym, side, qty=None, quote_amt=None, limit_px=None, maker=False):
        f = s.filters[sym]
        if maker and limit_px:
            conf = {"limit_limit_gtc": {"base_size": s._fmt(qty or quote_amt/limit_px, f["step"]), "limit_price": s._fmt(limit_px, f["tick"]), "post_only": True}}
        elif side == "BUY" and quote_amt: conf = {"market_market_ioc": {"quote_size": f"{quote_amt:.2f}"}}
        else: conf = {"market_market_ioc": {"base_size": s._fmt(qty*0.999, f["step"])}}
        return s._req("POST", "/orders", {"client_order_id": str(uuid.uuid4()), "product_id": sym, "side": side, "order_configuration": conf})
    def live_order_status(s, sym, oid): return s._req("GET", f"/orders/historical/{oid}")
    # ---- live helpers (Advanced Trade) ----
    def live_balances(s):
        out = {}; cur = None
        while True:
            d = s._req("GET", "/accounts?limit=250" + (f"&cursor={cur}" if cur else ""))
            for x in d.get("accounts", []):
                av = float(x["available_balance"]["value"]); hd = float((x.get("hold") or {}).get("value") or 0)
                if av or hd: out[x["currency"]] = (av, hd)
            if not d.get("has_next"): return out
            cur = d.get("cursor")
    def live_product(s, sym):
        p = s._req("GET", f"/products/{sym}")
        return dict(step=float(p["base_increment"]), tick=float(p["quote_increment"]), base_min=float(p.get("base_min_size") or 0),
                    quote_min=float(p.get("quote_min_size") or 1), qstep=float(p.get("quote_increment") or 0.01))
    def live_fee_rates(s):
        d = s._req("GET", "/transaction_summary"); ft = d.get("fee_tier") or {}
        return float(ft.get("taker_fee_rate") or 0.012), float(ft.get("maker_fee_rate") or 0.006)
    def _conf(s, sym, side, quote_amt=None, qty=None):
        f = s.live_product(sym)
        if side == "BUY" and quote_amt: return {"market_market_ioc": {"quote_size": s._fmt(quote_amt, max(f["qstep"], 0.01))}}, f
        return {"market_market_ioc": {"base_size": s._fmt(qty, f["step"])}}, f
    def live_preview(s, sym, side, quote_amt=None, qty=None):
        conf, f = s._conf(sym, side, quote_amt, qty)
        return s._req("POST", "/orders/preview", {"product_id": sym, "side": side, "order_configuration": conf})
    def live_market(s, sym, side, quote_amt=None, qty=None, wait=20):
        """market IOC; returns dict(status, filled_qty, avg_px, fee, quote) after confirming the fill"""
        conf, f = s._conf(sym, side, quote_amt, qty)
        r = s._req("POST", "/orders", {"client_order_id": str(uuid.uuid4()), "product_id": sym, "side": side, "order_configuration": conf})
        if not r.get("success"): return dict(status="REJECTED", error=r.get("error_response") or r)
        oid = r["success_response"]["order_id"]; t0 = time.time(); o = {}
        while time.time()-t0 < wait:
            time.sleep(1)
            o = s._req("GET", f"/orders/historical/{oid}").get("order", {})
            if o.get("status") in ("FILLED", "CANCELLED", "EXPIRED", "FAILED"): break
        q = float(o.get("filled_size") or 0)
        return dict(status=o.get("status"), order_id=oid, filled_qty=q, avg_px=float(o.get("average_filled_price") or 0), fee=float(o.get("total_fees") or 0),
                    quote=float(o.get("filled_value") or 0))
    def live_cancel(s, sym, oid): return s._req("POST", "/orders/batch_cancel", {"order_ids": [oid]})

ADAPTERS = {"binance": Binance, "coinbase": Coinbase}
