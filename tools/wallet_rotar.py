#!/usr/bin/env python3
"""Rotación del wallet caliente: genera uno NUEVO que solo existe en esta máquina y mueve todo el SOL del viejo al nuevo.
Para cuando la clave vieja se ha expuesto (por ejemplo, pegada en un chat o guardada en otra máquina).

  python3 tools/wallet_rotar.py --nuevo         # crea solana_wallet.new.json (solo lectura para ti) e imprime su dirección
  python3 tools/wallet_rotar.py --mover         # dry run: qué movería (SOL, cuentas vacías a cerrar, tokens que lo impiden)
  python3 tools/wallet_rotar.py --mover --yes   # cierra las cuentas vacías (rent), transfiere el SOL (menos 0,001 de reserva)
                                                #   al wallet nuevo y lo activa como solana_wallet.json (el viejo queda en .old)

Se niega si el bot está corriendo (primero ./stop.sh) o si hay tokens con saldo (posiciones abiertas o restos): primero libro plano."""
import os, sys, json, base64, subprocess

D = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); os.chdir(D); sys.path.insert(0, D)
NEW, OLD, CUR = "solana_wallet.new.json", "solana_wallet.old.json", "solana_wallet.json"
RESERVE_LAMPORTS, FEE_LAMPORTS = 1_000_000, 5_000     # 0.001 SOL stays behind + the transfer fee


def bot_running():
    try: r = subprocess.run(["pgrep", "-f", "python3 bot.p[y] --exchange"], capture_output=True, text=True, timeout=5); return bool(r.stdout.strip())
    except Exception: return False


def nuevo(path=NEW):
    from solders.keypair import Keypair
    if os.path.exists(path):
        kp = Keypair.from_bytes(bytes(json.load(open(path)))); print("ya existe", path, "->", kp.pubkey()); return str(kp.pubkey())
    kp = Keypair(); fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600); os.write(fd, json.dumps(list(bytes(kp))).encode()); os.close(fd)
    print("wallet nuevo creado en", path, "-> dirección", kp.pubkey()); return str(kp.pubkey())


def plan(live_sol):
    tb = live_sol.token_balances(); bal = live_sol.sol_balance(); empty = live_sol.empty_token_accounts()
    return {"from": live_sol.address(), "sol": bal, "tokens_with_balance": {m: v[0] for m, v in tb.items()}, "empty_atas": len(empty),
            "rent_back_sol": round(len(empty) * live_sol.ATA_RENT_SOL, 5)}


def transfer_tx(live_sol, to_addr, lamports):
    """signed SystemProgram transfer of `lamports` from the bot wallet to `to_addr` (base64)"""
    from solders.pubkey import Pubkey
    from solders.system_program import transfer, TransferParams
    from solders.transaction import Transaction
    from solders.hash import Hash
    owner = live_sol.kp().pubkey()
    ix = transfer(TransferParams(from_pubkey=owner, to_pubkey=Pubkey.from_string(to_addr), lamports=int(lamports)))
    bh = live_sol.rpc("getLatestBlockhash", [{"commitment": "confirmed"}])["value"]["blockhash"]
    return base64.b64encode(bytes(Transaction.new_signed_with_payer([ix], owner, [live_sol.kp()], Hash.from_string(bh)))).decode()


def mover(yes, new=NEW, old=OLD, cur=CUR):
    import live_sol
    from solders.keypair import Keypair
    if bot_running(): print("el bot está corriendo: primero ./stop.sh"); return 2
    if not os.path.exists(new): print("no hay wallet nuevo: primero --nuevo"); return 2
    to = str(Keypair.from_bytes(bytes(json.load(open(new)))).pubkey())
    p = plan(live_sol); print(json.dumps(p, indent=1))
    if p["tokens_with_balance"]: print("hay tokens con saldo (posiciones abiertas o restos): espera a libro plano o véndelos; no se mueve nada"); return 2
    if not yes: print(f"(dry run) movería ~{max(0.0, p['sol'] + p['rent_back_sol'] - RESERVE_LAMPORTS/1e9):.5f} SOL a {to}; con --yes se ejecuta"); return 0
    r = live_sol.close_empty_atas(dry_run=False); print("cuentas vacías cerradas:", r["closed"], "/", r["found"], "SOL recuperado:", r["sol_recovered"])
    lam = int(round(live_sol.sol_balance() * 1e9)) - RESERVE_LAMPORTS - FEE_LAMPORTS
    if lam <= 0: print("sin saldo suficiente para mover"); return 2
    sig = live_sol._send(transfer_tx(live_sol, to, lam)); print(f"transferidos {lam/1e9:.6f} SOL a {to}: tx {sig}")
    os.replace(cur, old); os.replace(new, cur); os.chmod(cur, 0o600); live_sol._kp = None
    print(f"wallet nuevo activado como {cur}; el viejo queda en {old} (bórralo cuando compruebes el saldo). Arranca el bot: nohup setsid ./run_forever.sh >/dev/null 2>&1 &")
    return 0


def main(argv):
    if "--nuevo" in argv: nuevo(); return 0
    if "--mover" in argv: return mover("--yes" in argv)
    print(__doc__); return 1


if __name__ == "__main__": sys.exit(main(sys.argv[1:]))
