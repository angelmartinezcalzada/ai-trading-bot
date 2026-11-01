#!/usr/bin/env python3
"""Recover the rent locked in EMPTY token accounts of the bot wallet (0.00203928 SOL each; 24 accounts ~ 4.7 $ on 31-oct).

    python3 tools/close_atas.py            # dry run: lists the zero-balance accounts and the SOL they hold
    python3 tools/close_atas.py --yes      # closes them (simulate -> send -> confirm); the rent returns to the wallet

Only accounts with a ZERO token balance are ever touched; an account that still holds tokens is never closed. Needs the
bot's solana_wallet.json (run from the bot folder, like the bot itself). Appends a JSON line to research/ata_close.jsonl."""
import os, sys, json, time
D = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); os.chdir(D); sys.path.insert(0, D)
def main(argv):
    import live_sol
    yes = "--yes" in argv
    r = live_sol.close_empty_atas(dry_run=not yes)
    sol = r["found"]*live_sol.ATA_RENT_SOL
    print(f"cuentas de token vacías: {r['found']}  (rent bloqueado ~{sol:.5f} SOL)")
    for m in r["mints"]: print("  ", m)
    if not yes: print("\n(dry run) para cerrarlas y recuperar el rent: python3 tools/close_atas.py --yes"); return 0
    print(f"cerradas: {r['closed']}/{r['found']}  SOL recuperado: {r['sol_recovered']}  fallidas: {len(r['failed'])}")
    for m, why in r["failed"]: print("  FALLO", m, why)
    os.makedirs("research", exist_ok=True)
    open("research/ata_close.jsonl", "a").write(json.dumps({"t": time.time(), **{k: v for k, v in r.items() if k != "mints"}})+"\n")
    return 0 if not r["failed"] else 1
if __name__ == "__main__": sys.exit(main(sys.argv[1:]))
