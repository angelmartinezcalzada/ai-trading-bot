#!/usr/bin/env python3
"""Fusiona la config local (la del dueño: modos, claves ajustadas) SOBRE la del repositorio tras un `git pull`:
    python3 tools/config_merge.py config.local.json config.json
Los valores locales mandan; las claves nuevas del repo se añaden. Nunca se pierde un ajuste hecho en la máquina."""
import json, sys, os
def merge(local, repo):
    out = dict(repo)
    for k, v in local.items():
        out[k] = merge(v, repo[k]) if isinstance(v, dict) and isinstance(repo.get(k), dict) else v
    return out
if __name__ == "__main__":
    loc, dst = sys.argv[1], sys.argv[2]
    merged = merge(json.load(open(loc)), json.load(open(dst)))
    tmp = dst + ".tmp"; json.dump(merged, open(tmp, "w"), indent=2, ensure_ascii=False); os.replace(tmp, dst); print("config fusionada: valores locales conservados")
