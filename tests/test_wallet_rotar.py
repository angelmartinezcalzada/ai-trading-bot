"""tools/wallet_rotar.py against a FAKE RPC: new keypair file, the SystemProgram transfer, the refusals and the file swap."""
import base64, json, os, sys, importlib.util
import pytest
from solders.keypair import Keypair
from solders.transaction import Transaction
import live_sol

spec = importlib.util.spec_from_file_location("wallet_rotar", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools", "wallet_rotar.py"))
wr = importlib.util.module_from_spec(spec); spec.loader.exec_module(wr)
SYSTEM = "11111111111111111111111111111111"


@pytest.fixture
def fake(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path); owner = Keypair(); st = {"sent": [], "bal": 0.05, "tokens": {}, "empty": []}
    def rpc(method, params):
        if method == "getBalance": return {"value": int(st["bal"] * 1e9)}
        if method == "getLatestBlockhash": return {"value": {"blockhash": "4vJ9JU1bJJE96FWSJKvHsmmFADCg4gpZQff4P3bkLKi"}}
        if method == "simulateTransaction": return {"value": {"err": None, "logs": []}}
        if method == "sendTransaction": st["sent"].append(params[0]); return "sig1"
        if method == "getSignatureStatuses": return {"value": [{"confirmationStatus": "confirmed", "err": None}]}
        raise AssertionError(method)
    monkeypatch.setattr(live_sol, "rpc", rpc); monkeypatch.setattr(live_sol, "kp", lambda: owner); monkeypatch.setattr(live_sol, "address", lambda: str(owner.pubkey()))
    monkeypatch.setattr(live_sol, "token_balances", lambda: st["tokens"]); monkeypatch.setattr(live_sol, "empty_token_accounts", lambda: st["empty"])
    monkeypatch.setattr(live_sol, "close_empty_atas", lambda dry_run=True, **k: {"closed": len(st["empty"]), "found": len(st["empty"]), "sol_recovered": 0.0, "failed": [], "mints": [], "dry_run": dry_run})
    monkeypatch.setattr(live_sol.time, "sleep", lambda s: None); monkeypatch.setattr(wr, "bot_running", lambda: False)
    json.dump(list(bytes(owner)), open("solana_wallet.json", "w"))
    return st, owner


def test_nuevo_creates_a_private_64_byte_keypair_once(fake, capsys):
    addr = wr.nuevo("w.json"); raw = json.load(open("w.json"))
    assert len(raw) == 64 and str(Keypair.from_bytes(bytes(raw)).pubkey()) == addr and oct(os.stat("w.json").st_mode)[-3:] == "600"
    assert wr.nuevo("w.json") == addr                                                     # never overwritten


def test_transfer_tx_is_a_system_transfer_of_the_requested_lamports(fake):
    st, owner = fake; to = Keypair().pubkey()
    tx = Transaction.from_bytes(base64.b64decode(wr.transfer_tx(live_sol, str(to), 123456)))
    keys = list(tx.message.account_keys); ix = tx.message.instructions[0]
    assert str(keys[ix.program_id_index]) == SYSTEM and str(keys[0]) == str(owner.pubkey())
    data = bytes(ix.data); assert int.from_bytes(data[:4], "little") == 2 and int.from_bytes(data[4:12], "little") == 123456   # 2 = Transfer
    assert str(keys[ix.accounts[1]]) == str(to) and tx.verify_and_hash_message()


def test_mover_refuses_running_bot_missing_new_wallet_and_open_tokens(fake, monkeypatch, capsys):
    st, owner = fake
    assert wr.mover(True, new="n.json", old="o.json", cur="solana_wallet.json") == 2                 # no new wallet
    wr.nuevo("n.json")
    monkeypatch.setattr(wr, "bot_running", lambda: True); assert wr.mover(True, new="n.json", old="o.json", cur="solana_wallet.json") == 2
    monkeypatch.setattr(wr, "bot_running", lambda: False); st["tokens"] = {"MINT": (5, 6)}
    assert wr.mover(True, new="n.json", old="o.json", cur="solana_wallet.json") == 2 and st["sent"] == []
    st["tokens"] = {}; assert wr.mover(False, new="n.json", old="o.json", cur="solana_wallet.json") == 0 and st["sent"] == []   # dry run sends nothing
    assert "dry run" in capsys.readouterr().out


def test_mover_yes_transfers_balance_minus_reserve_and_swaps_files(fake):
    st, owner = fake; st["empty"] = [("acc", live_sol.TOKEN_PROGS[0], "M1")]
    new_addr = wr.nuevo("n.json")
    assert wr.mover(True, new="n.json", old="o.json", cur="solana_wallet.json") == 0 and len(st["sent"]) == 1
    tx = Transaction.from_bytes(base64.b64decode(st["sent"][0])); ix = tx.message.instructions[0]; keys = list(tx.message.account_keys)
    assert int.from_bytes(bytes(ix.data)[4:12], "little") == int(0.05 * 1e9) - wr.RESERVE_LAMPORTS - wr.FEE_LAMPORTS and str(keys[ix.accounts[1]]) == new_addr
    assert not os.path.exists("n.json") and os.path.exists("o.json") and str(Keypair.from_bytes(bytes(json.load(open("solana_wallet.json")))).pubkey()) == new_addr
    assert json.load(open("o.json")) == list(bytes(owner))
