#!/usr/bin/env python3
"""Tabla de las wallets insider mas fiables segun insider_rank.json (solo lectura; no toca la red ni el bot).

  python3 tools/insider_rank_report.py              # top 20 del ultimo ranking (aunque este obsoleto, lo avisa)
  python3 tools/insider_rank_report.py --top 50
  python3 tools/insider_rank_report.py --build      # recalcula el ranking offline (sin Solana Tracker) y lo imprime"""
import os, sys, time
D = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); os.chdir(D); sys.path.insert(0, D)
import insider_rank as ir

if __name__ == "__main__":
    a = sys.argv[1:]; n = int(a[a.index("--top")+1]) if "--top" in a else 20
    doc = ir.build(".") if "--build" in a else ir._load_json(ir.F_RANK, None)
    if doc and ir.load(".") is None and "--build" not in a: print("AVISO: ranking obsoleto o invalido (hace %.0f min): insider.py usa el ranking antiguo" % ((time.time()-(doc.get("t") or 0))/60))
    print(ir.table(doc, n))
