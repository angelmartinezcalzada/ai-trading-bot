"""Solana LIVE executor (Jupiter): quote -> swap tx -> local sign -> simulate -> send (public RPC) -> confirm.
Hot wallet: solana_wallet.json (chmod 600, never printed). No withdrawals: only Jupiter swaps from/to SOL."""
import json, time, base64, os, logging, requests
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction
log = logging.getLogger("meme")
SOL = "So11111111111111111111111111111111111111112"
RPCS = [os.environ.get("SOLANA_RPC") or "https://api.mainnet-beta.solana.com", "https://solana-rpc.publicnode.com"]
JUP = "https://lite-api.jup.ag/swap/v1"
TOKEN_PROGS = ["TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA", "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"]
WALLET = os.path.join(os.path.dirname(os.path.abspath(__file__)), "solana_wallet.json")
_kp = None
def kp():
    global _kp
    if _kp is None: _kp = Keypair.from_bytes(bytes(json.load(open(WALLET))))
    return _kp
def address(): return str(kp().pubkey())
def rpc(method, params):
    err = None
    for u in RPCS:
        for i in range(3):
            try:
                h = requests.post(u, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, timeout=10)
                if h.status_code == 429: err = "429"; time.sleep(2+2*i); continue
                r = h.json()
                if "error" in r:
                    err = r["error"]
                    if "personal token" in str(err): break
                    time.sleep(1); continue
                return r["result"]
            except Exception as e: err = e; time.sleep(1)
    raise RuntimeError(f"rpc {method}: {err}")
def sol_balance(): return rpc("getBalance", [address(), {"commitment": "confirmed"}])["value"]/1e9
def token_balances():
    """{mint: (raw, decimals)} for all non-zero SPL / Token-2022 accounts"""
    out = {}
    for pg in TOKEN_PROGS:
        for a in rpc("getTokenAccountsByOwner", [address(), {"programId": pg}, {"encoding": "jsonParsed", "commitment": "confirmed"}])["value"]:
            i = a["account"]["data"]["parsed"]["info"]; ta = i["tokenAmount"]
            if int(ta["amount"]) > 0: out[i["mint"]] = (out.get(i["mint"], (0, 0))[0] + int(ta["amount"]), ta["decimals"])
    return out
def slippage_bps(size_usd, liq_usd, impact_pct=0.0, urgent=False):
    """per-coin slippage: base 100bps + size/liquidity depth term + 2x quoted impact; urgent exits allow more"""
    b = 100 + 2e4*size_usd/max(liq_usd, 1) + 200*max(0, impact_pct)
    return int(min(1500 if urgent else 800, max(100, b)))
def quote(inp, out, amount, slip):
    import jupr
    r = jupr.request("GET", JUP + "/quote", params=dict(inputMint=inp, outputMint=out, amount=str(int(amount)), slippageBps=int(slip)), timeout=15).json()
    if "outAmount" not in r: raise RuntimeError(f"no quote: {r}")
    return r
def sellable(m, raw_out, slip, max_rt_pct, in_lamports):
    """sell-ability before buying: a token->SOL route must exist for the bought amount and the round trip must lose <= max_rt_pct"""
    try: q = quote(m, SOL, raw_out, slip)
    except Exception as e: return False, f"no_sell_route {e}"
    rt = (1-int(q["outAmount"])/in_lamports)*100
    return rt <= max_rt_pct, f"rt={rt:.2f}%"
def prio_lamports(floor=5000, cap=100000, cu=300000):
    """dynamic priority fee: p75 of recent non-zero microlamports/CU on Jupiter's program, x expected CU, clipped"""
    try:
        r = [x["prioritizationFee"] for x in rpc("getRecentPrioritizationFees", [["JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4"]]) if x["prioritizationFee"] > 0]
        if not r: return floor
        r.sort(); return int(max(floor, min(cap, r[int(len(r)*0.75)]*cu/1e6)))
    except Exception: return floor
_FEES = {}
def tx_fee_sol(sig):
    if sig in _FEES: return _FEES[sig]
    for _ in range(3):
        try:
            t = rpc("getTransaction", [sig, {"maxSupportedTransactionVersion": 0, "encoding": "json", "commitment": "confirmed"}])
            if t: _FEES[sig] = t["meta"]["fee"]/1e9; return _FEES[sig]
        except Exception: pass
        time.sleep(2)
    return None
def prio_for(urgent, base=None):
    """priority fee cap: routine orders use the p75 estimate (<= 100k lamports); urgent exits (rug / liquidity pull / stop / kill)
    pay up to 10x that at 'veryHigh' (<= 1,000,000 lamports ~ $0.10) so the exit lands while everyone else is leaving the pool."""
    base = base or prio_lamports()
    return (min(1_000_000, max(base*10, 100_000)), "veryHigh") if urgent else (base, "medium")
def swap(q, max_prio_lamports=None, urgent=False):
    """build -> sign locally -> simulate -> send -> confirm. returns signature or raises."""
    cap, level = prio_for(urgent, max_prio_lamports)
    body = {"quoteResponse": q, "userPublicKey": address(), "wrapAndUnwrapSol": True, "dynamicComputeUnitLimit": True, "dynamicSlippage": False,
            "prioritizationFeeLamports": {"priorityLevelWithMaxLamports": {"maxLamports": cap, "priorityLevel": level}}}
    r = __import__("jupr").request("POST", JUP + "/swap", json=body, timeout=20).json()
    if "swapTransaction" not in r: raise RuntimeError(f"swap build: {r}")
    tx = VersionedTransaction.from_bytes(base64.b64decode(r["swapTransaction"]))
    stx = VersionedTransaction(tx.message, [kp()]); raw = base64.b64encode(bytes(stx)).decode()
    sim = rpc("simulateTransaction", [raw, {"encoding": "base64", "sigVerify": True, "commitment": "processed"}])["value"]
    if sim.get("err"): raise RuntimeError(f"simulation failed: {sim['err']} {(sim.get('logs') or [])[-3:]}")
    sig = rpc("sendTransaction", [raw, {"encoding": "base64", "skipPreflight": True, "maxRetries": 3}])
    t0 = time.time()
    while time.time()-t0 < 45:
        st = rpc("getSignatureStatuses", [[sig], {"searchTransactionHistory": False}])["value"][0]
        if st:
            if st.get("err"): raise RuntimeError(f"tx failed on-chain {sig}: {st['err']}")
            if st.get("confirmationStatus") in ("confirmed", "finalized"): return sig
        time.sleep(2)
        if int(time.time()-t0) % 10 < 2:
            try: rpc("sendTransaction", [raw, {"encoding": "base64", "skipPreflight": True, "maxRetries": 0}])
            except Exception: pass
    # late-landing guard: re-check with full history before declaring failure (19:48 USELESS sold on-chain but was reported failed)
    for _ in range(5):
        try:
            st = rpc("getSignatureStatuses", [[sig], {"searchTransactionHistory": True}])["value"][0]
            if st:
                if st.get("err"): raise RuntimeError(f"tx failed on-chain {sig}: {st['err']}")
                if st.get("confirmationStatus") in ("confirmed", "finalized"): return sig
        except RuntimeError: raise
        except Exception: pass
        time.sleep(3)
    raise RuntimeError(f"not confirmed in 75s {sig}")
# ---------------- token-account rent recovery (SPL CloseAccount, instruction 9) ----------------
ATA_RENT_SOL = 0.00203928
def empty_token_accounts():
    """[(account_pubkey, token_program, mint)] of the wallet's token accounts with a ZERO balance (SPL + Token-2022)."""
    out = []
    for pg in TOKEN_PROGS:
        for a in rpc("getTokenAccountsByOwner", [address(), {"programId": pg}, {"encoding": "jsonParsed", "commitment": "confirmed"}])["value"]:
            i = a["account"]["data"]["parsed"]["info"]
            if int(i["tokenAmount"]["amount"]) == 0 and i.get("state", "initialized") == "initialized": out.append((a["pubkey"], pg, i["mint"]))
    return out
def _close_tx(accts):
    """signed legacy tx closing the given zero-balance token accounts; the rent lamports go back to the wallet (destination = owner)"""
    from solders.instruction import Instruction, AccountMeta
    from solders.pubkey import Pubkey
    from solders.transaction import Transaction
    from solders.hash import Hash
    owner = kp().pubkey()
    ixs = [Instruction(Pubkey.from_string(pg), bytes([9]), [AccountMeta(Pubkey.from_string(pk), False, True), AccountMeta(owner, False, True), AccountMeta(owner, True, False)])
           for pk, pg, _ in accts]
    bh = rpc("getLatestBlockhash", [{"commitment": "confirmed"}])["value"]["blockhash"]
    tx = Transaction.new_signed_with_payer(ixs, owner, [kp()], Hash.from_string(bh))
    return base64.b64encode(bytes(tx)).decode()
def _send(raw, timeout=40):
    """simulate -> send -> confirm (no Jupiter involved). Raises on a simulation error, an on-chain error or a timeout."""
    sim = rpc("simulateTransaction", [raw, {"encoding": "base64", "sigVerify": True, "commitment": "processed"}])["value"]
    if sim.get("err"): raise RuntimeError(f"simulation failed: {sim['err']} {(sim.get('logs') or [])[-2:]}")
    sig = rpc("sendTransaction", [raw, {"encoding": "base64", "skipPreflight": True, "maxRetries": 3}])
    t0 = time.time()
    while time.time()-t0 < timeout:
        st = rpc("getSignatureStatuses", [[sig], {"searchTransactionHistory": False}])["value"][0]
        if st:
            if st.get("err"): raise RuntimeError(f"tx failed on-chain {sig}: {st['err']}")
            if st.get("confirmationStatus") in ("confirmed", "finalized"): return sig
        time.sleep(2)
    raise RuntimeError(f"not confirmed in {timeout}s {sig}")
def close_empty_atas(dry_run=True, only=None, skip=(), batch=12):
    """Close zero-balance token accounts so their rent (ATA_RENT_SOL each) returns to the wallet. Never touches an account that
    still holds tokens. `only`: restrict to these mints; `skip`: mints to leave alone (a position being sold right now).
    A batch whose simulation fails is retried one account at a time, so one odd Token-2022 account never blocks the rest.
    Returns dict(found, closed, sol_recovered, sigs, failed=[(mint, why)], mints, dry_run)."""
    accts = [x for x in empty_token_accounts() if (only is None or x[2] in only) and x[2] not in skip]
    res = dict(found=len(accts), closed=0, sol_recovered=0.0, sigs=[], failed=[], mints=[x[2] for x in accts], dry_run=dry_run)
    if dry_run or not accts: return res
    try: bal0 = sol_balance()
    except Exception: bal0 = None
    def run(chunk):
        try: res["sigs"].append(_send(_close_tx(chunk))); res["closed"] += len(chunk)
        except Exception as e:
            if len(chunk) == 1: res["failed"].append((chunk[0][2], str(e)[:120]))
            else:
                for c in chunk: run([c])
    for i in range(0, len(accts), batch): run(accts[i:i+batch])
    try: res["sol_recovered"] = round(sol_balance()-bal0, 6) if bal0 is not None else None
    except Exception: res["sol_recovered"] = None
    log.info("[solana] ATA close: %d/%d closed, SOL back %s, %d failed", res["closed"], res["found"], res["sol_recovered"], len(res["failed"]))
    return res
