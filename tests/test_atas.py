"""live_sol.close_empty_atas: builds real CloseAccount transactions against a FAKE RPC (no network, no wallet of the bot)."""
import base64, json, sys, types
import pytest
from solders.keypair import Keypair
from solders.transaction import Transaction
import live_sol

SPL, T22 = live_sol.TOKEN_PROGS
OWNER = Keypair()

def acct(pk, mint, amount, pg):
    return {"pubkey": pk, "account": {"data": {"parsed": {"info": {"mint": mint, "state": "initialized", "tokenAmount": {"amount": str(amount), "decimals": 6}}}}}}

@pytest.fixture
def fake(monkeypatch):
    """fake RPC: 3 empty accounts (2 SPL + 1 Token-2022), 1 account with tokens; records every sent transaction"""
    acc = {SPL: [acct(str(Keypair().pubkey()), "MintA", 0, SPL), acct(str(Keypair().pubkey()), "MintB", 0, SPL), acct(str(Keypair().pubkey()), "MintHeld", 5, SPL)],
           T22: [acct(str(Keypair().pubkey()), "MintC", 0, T22)]}
    st = {"sent": [], "bal": [1.0, 1.006], "fail_mints": set(), "sim_calls": 0}
    def rpc(method, params):
        if method == "getTokenAccountsByOwner": return {"value": acc[params[1]["programId"]]}
        if method == "getBalance": return {"value": int(st["bal"].pop(0)*1e9) if len(st["bal"]) > 1 else int(st["bal"][0]*1e9)}
        if method == "getLatestBlockhash": return {"value": {"blockhash": "4vJ9JU1bJJE96FWSJKvHsmmFADCg4gpZQff4P3bkLKi"}}
        if method == "simulateTransaction":
            st["sim_calls"] += 1; tx = Transaction.from_bytes(base64.b64decode(params[0]))
            keys = [str(k) for k in tx.message.account_keys]
            bad = [k for k in keys if any(a["pubkey"] == k and a["account"]["data"]["parsed"]["info"]["mint"] in st["fail_mints"] for L in acc.values() for a in L)]
            return {"value": {"err": {"InstructionError": [0, "Custom"]} if bad else None, "logs": []}}
        if method == "sendTransaction": st["sent"].append(params[0]); return "sig%d" % len(st["sent"])
        if method == "getSignatureStatuses": return {"value": [{"confirmationStatus": "confirmed", "err": None}]}
        raise AssertionError(method)
    monkeypatch.setattr(live_sol, "rpc", rpc); monkeypatch.setattr(live_sol, "kp", lambda: OWNER); monkeypatch.setattr(live_sol, "address", lambda: str(OWNER.pubkey()))
    monkeypatch.setattr(live_sol.time, "sleep", lambda s: None)
    return st

def test_dry_run_lists_only_zero_balance_accounts(fake):
    r = live_sol.close_empty_atas(dry_run=True)
    assert r["found"] == 3 and sorted(r["mints"]) == ["MintA", "MintB", "MintC"] and r["closed"] == 0 and not fake["sent"]

def test_close_builds_one_close_instruction_per_account_with_rent_to_owner(fake):
    r = live_sol.close_empty_atas(dry_run=False)
    assert r["closed"] == 3 and len(fake["sent"]) == 1 and r["failed"] == [] and r["sol_recovered"] == pytest.approx(0.006)
    tx = Transaction.from_bytes(base64.b64decode(fake["sent"][0])); keys = list(tx.message.account_keys)
    assert len(tx.message.instructions) == 3 and str(keys[0]) == str(OWNER.pubkey())
    for ix in tx.message.instructions:
        assert bytes(ix.data) == b"\x09"                                           # CloseAccount
        assert str(keys[ix.program_id_index]) in (SPL, T22)
        a, dest, auth = [keys[i] for i in ix.accounts]
        assert str(dest) == str(OWNER.pubkey()) and str(auth) == str(OWNER.pubkey())   # rent goes back to the wallet, owner signs
    assert tx.verify_and_hash_message()                                            # signed by the owner

def test_only_and_skip_filters(fake):
    r = live_sol.close_empty_atas(dry_run=False, only={"MintA", "MintC"}, skip={"MintC"})
    assert r["mints"] == ["MintA"] and r["closed"] == 1

def test_failed_batch_is_retried_one_by_one(fake):
    fake["fail_mints"].add("MintB")
    r = live_sol.close_empty_atas(dry_run=False)
    assert r["closed"] == 2 and [m for m, _ in r["failed"]] == ["MintB"] and len(fake["sent"]) == 2 and fake["sim_calls"] == 4   # batch sim fails -> 3 single sims

def test_batches_are_capped(fake, monkeypatch):
    acc_many = [acct(str(Keypair().pubkey()), f"M{i}", 0, SPL) for i in range(30)]
    monkeypatch.setattr(live_sol, "empty_token_accounts", lambda: [(a["pubkey"], SPL, a["account"]["data"]["parsed"]["info"]["mint"]) for a in acc_many])
    r = live_sol.close_empty_atas(dry_run=False, batch=12)
    assert r["closed"] == 30 and len(fake["sent"]) == 3
