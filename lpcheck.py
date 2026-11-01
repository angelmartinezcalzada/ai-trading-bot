"""On-chain LP-lock proof for pools GoPlus/RugCheck can't score. Fail-closed: return 0.0 unless burn is PROVEN.
PumpSwap (pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA): pool stores lp_supply (minted at creation); burned% =
1 - current LP mint supply / lp_supply, plus LP held by the pool's own program-derived/lp-burn accounts is NOT counted.
CLMM/DLMM/Whirlpool: position NFTs per pool, not enumerable reliably on public RPC -> 0.0 (still rejected)."""
import base64, struct, requests
PUMPSWAP = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
def b58(b):
    n = int.from_bytes(b, "big"); s = ""
    while n: n, r = divmod(n, 58); s = B58[r] + s
    return "1" * (len(b) - len(b.lstrip(b"\0"))) + s
def pumpswap_burn_pct(mint, rpc):
    try:
        pairs = requests.get("https://api.dexscreener.com/tokens/v1/solana/" + mint, timeout=10).json() or []
        ps = sorted([p for p in pairs if p.get("dexId") == "pumpswap"], key=lambda p: -((p.get("liquidity") or {}).get("usd") or 0))
        if not ps: return 0.0, "no_pumpswap_pool"
        top_all = max((p.get("liquidity") or {}).get("usd") or 0 for p in pairs)
        if ((ps[0].get("liquidity") or {}).get("usd") or 0) < 0.8 * top_all: return 0.0, "main_liq_not_pumpswap"
        pool = ps[0]["pairAddress"]
        v = (rpc("getAccountInfo", [pool, {"encoding": "base64"}]) or {}).get("value")
        if not v or v.get("owner") != PUMPSWAP: return 0.0, "pool_owner_mismatch"
        d = base64.b64decode(v["data"][0])
        base, quote, lpm = b58(d[43:75]), b58(d[75:107]), b58(d[107:139])
        if mint not in (base, quote): return 0.0, "mint_mismatch"
        lp_supply = struct.unpack("<Q", d[203:211])[0]
        cur = int(((rpc("getTokenSupply", [lpm]) or {}).get("value") or {}).get("amount") or -1)
        if lp_supply <= 0 or cur < 0 or cur > lp_supply: return 0.0, "lp_data_bad"
        return round(100 * (1 - cur / lp_supply), 1), f"pumpswap pool={pool} lp_burned"
    except Exception as e:
        return 0.0, f"err:{e}"
