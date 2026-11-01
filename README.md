# Proyecto: bot de trading autónomo 24/7 (memecoins de Solana)

> Documento para compartir con otra IA. No contiene claves, wallet ni URLs privadas. El código completo está en `ai-trading-bot-share.zip`.

## 0. Estado del MVP (31-oct-2026, sesión con Keel + Coinversa; revisado 21:45 UTC)
- **Nueva pata Hyperliquid (`hl_leg/`)**: regla de tendencia SuperTrend+Bollinger 1d sobre el top-15 de perps por volumen, con el
  top-15 re-elegido cada semana **sin mirar el futuro**. Evidencia honesta en Keel: fuera de muestra (abr→oct 2026) Sharpe 1,15,
  +43,5 %, DD −30 %; ventana completa 2024-08→2026-10 Sharpe 0,76, +91 %, DD −58 %, 6/10 trimestres positivos. En paper en Keel
  desde el 31-oct (`hl_leg/hl_paper.json`). Real solo con ≥150 $ y tras ≥21 días / ≥20 evaluaciones con paridad. Detalle: `hl_leg/README.md`.
- **Aviso honesto**: los Sharpe 1,9-2,0 que aparecieron durante la sesión venían de un universo resuelto en julio-2026 (dentro de la
  ventana fuera de muestra): supervivencia, no ventaja. "Muy buen rendimiento" **no** está demostrado; "ventaja pequeña medida sin
  trampas" sí. La misma regla sobre memecoins en perps no es claramente peor que sobre el top-15 causal; lo que dice que las memecoins
  pierden es el historial real del bot (PF 0,44).
- **Coinversa** = capa de riesgo/contexto (sesgo de cohortes, apalancamiento, clusters de liquidación) para la revisión CFO y el
  panel (`/api/hl`); NO es señal: el estudio de 30 días no encontró poder predictivo (`research/coinversa_study.py`).
- **memebot.py**: 18 correcciones verificadas por revisión adversarial (escaneos de 650-780 s, puerta EV real, kill switch, write-off
  con evidencia, cerebro evaluado con honestidad, …), vetos/tamaños/stops intactos. Tests: `python3 -m pytest -q tests/` (51).
- **1-nov**: panel v2 en vivo en `/` (`DASHBOARD.md`, solo datos reales con frescura por bloque); **Director** (`director.py`): el bot
  decide jugadas, umbrales, tamaño, horas, perfil de salida y tope diario con evidencia, **solo endureciendo** los topes (24 h en sombra);
  cerebro v2 (logística + Beta, p pesimista, EV neto de costes fijos); recuperación del rent de las cuentas de token (`tools/close_atas.py`,
  ~4,7 $ bloqueados; el memebot cierra cada cuenta tras vender). Tests: 97.
- **1-nov (tarde): bot autosuficiente.** Sin operador externo: `operador.py` hace la revisión horaria (salud, equity, escaneos,
  errores, Director, cerebro, Coinversa), toma solo acciones seguras (rent de ATAs, procesos colgados, Director obsoleto, logs),
  escribe `DECISIONS.md`, emite alertas (`alerts.jsonl` + `ALERT_CMD`) y el informe diario. Instalación en un comando (`install.sh`),
  parada ordenada (`stop.sh`), tarjeta "Operador automático" en el panel. Guía: `OPERACION.md`. Tests: 105.
- Diseño y supuestos: `../docs/superpowers/specs/2026-10-31-trading-bot-mvp-design.md` y `2026-10-31-director-brain-design.md`.
  Registro de decisiones: `DECISIONS.md`. Operación: `OPERACION.md` (el traspaso a Grok queda superado).

## 1. Objetivo
Bot autónomo 24/7 que opera memecoins de Solana con dinero real (saldo ~48,5 $) con el objetivo de hacer crecer el saldo hacia ~1.000 € (sin garantía). Se gestiona "como un CFO": revisión horaria, panel cada 15 min y una rutina de automejora del modelo cada 2 h.

## 2. Mercados
| Mercado | Modo | Estado |
|---|---|---|
| Solana memecoins (Jupiter swaps) | **REAL** | ~48,5 $ en cash, sin posiciones |
| Coinbase (SOL-USD) | REAL | ~3,36 $, detenido (halt), clave sin permiso de retiro |
| Binance | PAPEL | ~998,8 $ virtuales, 3 cierres, −1,20 $ |

## 3. Arquitectura / ficheros
- `memebot.py` – núcleo Solana: escaneo de pares, vetos antiestafa, scoring, modelo, entradas/salidas, pump-play y copytrade.
- `scam.py` – chequeos RugCheck (score, LP, mint/freeze, top10, insiders, honeypot).
- `live_sol.py` – ejecución real vía Jupiter (firma con wallet local, no incluida).
- `brain.py`, `train_model.py`, `features.py`, `eval_solana.py` – modelo de decisión (ganancia esperada) y evaluación out-of-sample.
- `copytrade_paper.py`, `smart_money.py`, `insider.py` – copytrade/insiders (papel).
- `bot.py`, `exchanges.py`, `live_cb.py`, `swing.py` – bot CEX (Coinbase/Binance).
- `dashboard.py`, `live_view.py`, `update_canvas.py` – panel.
- `research/` – estudios (niveles, pump, scams, comparación de modelos, etc.).
- `DECISIONS.md` – registro de cada estudio y cambio (fuente de verdad del razonamiento).
- `data/` – CSV de operaciones y equity.

## 4. Estrategia
- Fuentes de candidatos: DexScreener + GeckoTerminal (pools Solana por volumen 24h) + listas de Jupiter (top traded 1h/24h, organic score, trending). Excluye stables, SOL staked y wrapped. ~316–335 pares/escaneo, ~124 líquidos.
- Entra solo si el modelo predice ganancia esperada > 1% **y** ≥ 3× el coste ida+vuelta, con slippage ≤ 100 pb (1%).
- Límites fijos: liquidez mínima 50k $, coste ida-vuelta máx 3%, stop diario 5%.

## 5. Vetos (nunca se relajan)
RugCheck con score ≤ 20; ≥ 5.000 holders; LP bloqueada/quemada; sin mint/freeze authority; no honeypot; límite de concentración top-10; blacklist de creadores en serie.
Fallback si RugCheck cae: GoPlus (sin clave) + chequeo on-chain de mint/freeze; rechaza si falta cualquier dato; LP solo válida si quemada en pool clásico (CLMM/pumpswap rechazados); vuelve a RugCheck automáticamente.

## 6. Salidas (modo "trail")
Tamaño 8% del equity por operación; hard stop −6% neto; trailing 12% desde máximo. Hay salidas auxiliares (whale_spike_lock, kill_switch, sell_pressure, early_exit, protect_lock).

## 7. Modelo y resultados out-of-sample
- Modelo promovido (conservador, umbral >1%): **+2,57%/operación, PF 3,13, 19 trades** OOS, vs anterior +0,48%, PF 1,27, 90 trades. ~4× menos operaciones.
- Refresco posterior: +1,70% vs baseline −3,19% (695 muestras).
- Rutina cada 2 h: autocrítica → reentrena → prueba una mejora contra el peor error → promueve solo si mejoran retorno medio Y PF OOS; nunca relaja vetos/tamaño/stops.

## 8. Pump-play (PAPEL)
Compra temprana de monedas "hype" e intenta salir antes del rug. En real perdió (PF < 1) y se pasó a papel. Reactivado hoy solo en simulación; 0 cierres aún. Solo volvería a real con ≥ 20 cierres rentables.

## 9. Copytrade (PAPEL)
Copia carteras "smart money". Resultados muy malos (rugs). Hoy se le añadió el mismo veto antirug que el bot real. No apto para real (requisito: ≥ 20 cierres y PF > 1,3).

## 10. Resultados / PnL actuales
- Solana REAL (histórico, incluye pump-play real antiguo): 64 cierres, PnL -1.65 $, 21 ganadores, PF 0.44
- Copytrade papel: 36 cierres, PnL -32.74 $, 15 ganadores, PF 0.18
- Coinbase real: 1 cierre, −0,66 $; detenido. Binance papel: 3 cierres, −1,20 $.
- Mejor moneda histórica: POPCAT (3/3, +4,5%), luego Fartcoin; pero operar solo con ellas pierde en simulación de 11 días.

## 11. Cambios de hoy (31-oct-2026)
- Nuevas fuentes de monedas (GeckoTerminal + Jupiter).
- Fallback RugCheck → GoPlus + on-chain.
- Estudio de liquidez: los rechazados solo por liquidez se hundieron 78–84% vs 2% → se mantiene 50k.
- Modelo nuevo promovido; rutina de automejora con autocrítica.
- Pump-play reactivado en papel.
- Cambios propuestos por otro agente (aprobados): veto antirug en copytrade; entrada solo si ganancia esperada ≥ 3× coste y slippage ≤ 100 pb; salidas sin cambio (datos insuficientes). Reinicio 18:26 (Madrid).

## 12. Problemas abiertos
1. **Sin operaciones reales desde la 01:19 (~17 h)**: ningún candidato pasa los vetos (liquidez, LP no bloqueada, top-10, mint/freeze activos, pocos holders).
2. **RugCheck caído/lento desde ~13:50** (un escaneo tardó 656 s para 58 informes); el fallback rechaza todas las pools CLMM/pumpswap porque no puede verificar el bloqueo de LP.
3. ¿Cómo verificar bloqueos de LP en CLMM/pumpswap sin relajar el veto?
4. ¿Cómo aumentar operaciones seguras sin empeorar PF? Salidas auxiliares (kill_switch, sell_pressure, early_exit) pierden casi siempre; protect_take ganó 4/4.

## 13. Extractos clave de código
### Salida trailing (memebot.py)
```python
def trail_exit(x, p, c):
    """TikTok mode: hard stop -hard_stop_pct net of fees from cost; exit when price falls trail_pct_tt% from peak."""
    net = x*p["raw"]/10**p["dec"]/p["cost"]-1
    if net <= -c.get("hard_stop_pct", 6)/100: return f"hard_stop net={net*100:+.1f}%"
    if x <= p["best"]*(1-c.get("trail_pct_tt", 12)/100) and p["best"] > p.get("entry", x): return f"trail12 peak={p['best']:.6g} net={net*100:+.1f}%"
    return None
```
### Fallback RugCheck → GoPlus (memebot.py)
```python
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
```
### Veto antiestafa (scam.py)
```python
def rc(m): return _get(f"https://api.rugcheck.xyz/v1/tokens/{m}/report", 600) or {}
def blacklist():
    try: return set(json.load(open(BL)))
    except Exception: return set()
def ban(*addrs):
    b = blacklist() | {a for a in addrs if a}; json.dump(sorted(b), open(BL, "w"))
STABLE = re.compile(r"^(W?USD|USDT|USDC|DAI|PYUSD|EURC|UDT|USTC?)")
def check(m, sym, price, c=None, roundtrip=None):
    c = c or {}; f = []; S = (sym or "").upper()
    vid, vsym = verified(); j = jup(m); r = rc(m)
    if m in vid: return []                                                    # Jupiter-verified mint
    try: px = float(price)
    except Exception: px = 0
    if STABLE.match(S) and abs(px-1) > 0.03: f.append("fake_stable")
    if S in vsym or S.lstrip("$W") in vsym and len(S) >= 3: f.append("clone_ticker")
    tf = (r.get("transferFee") or {}).get("pct") or 0
    if tf > c.get("max_sell_tax_pct", 3): f.append(f"sell_tax{tf}")
    if roundtrip is not None and roundtrip > c.get("max_roundtrip_loss_pct", 6): f.append(f"honeypot_rt{roundtrip:.1f}")
    lp = max([(mk.get("lp") or {}).get("lpLockedPct") or 0 for mk in r.get("markets") or []] or [0])
    if r and lp < c.get("min_lp_locked_pct", 90): f.append(f"lp_unlocked{lp:.0f}")
    sup = float((r.get("token") or {}).get("supply") or 0)/10**((r.get("token") or {}).get("decimals") or 6)
    dev_pct = (r.get("creatorBalance") or 0)/sup*100 if sup else 0
    if dev_pct > c.get("max_dev_pct", 5): f.append(f"dev_holds{dev_pct:.0f}%")
    au = j.get("audit") or {}
    if (au.get("devMints") or 0) >= c.get("max_dev_mints", 20): f.append(f"serial_dev{au['devMints']}")
    ins = r.get("graphInsidersDetected") or 0
    if ins >= c.get("max_insiders", 5): f.append(f"insiders{ins}")
    if (au.get("topHoldersPercentage") or 0) > c.get("max_top_holders_pct", 35): f.append(f"concentrated{au['topHoldersPercentage']:.0f}%")
    s24 = j.get("stats24h") or {}; s1 = j.get("stats1h") or {}
    if j and (j.get("organicScore") or 0) < c.get("min_organic_score", 10): f.append(f"wash_organic{j.get('organicScore') or 0:.0f}")
    tx = (s1.get("numBuys") or 0)+(s1.get("numSells") or 0); tr = s1.get("numTraders") or s1.get("numOrganicBuyers") or 0
    if tx > 200 and tr and tr/tx < c.get("min_trader_tx_ratio", 0.08): f.append(f"wash_traders{tr}/{tx}")
    ca = j.get("createdAt") or (j.get("firstPool") or {}).get("createdAt")
    if ca:
        import datetime as dt
        age = (time.time()-dt.datetime.fromisoformat(ca.replace("Z", "+00:00")).timestamp())/3600
        if age < c.get("min_age_h", 1): f.append(f"too_new{age:.1f}h")
    if (r.get("tokenMeta") or {}).get("mutable"): f.append("mutable_meta")
    if r.get("mintAuthority"): f.append("mint_auth")
    if r.get("freezeAuthority"): f.append("freeze_auth")
    if (r.get("score_normalised") or 0) > c.get("max_rugcheck_score", 60): f.append(f"rc_score{r['score_normalised']}")
    if r.get("rugged"): f.append("rugged")
    bl = blacklist()
    if r.get("creator") in bl or j.get("dev") in bl: f.append("blacklisted_creator")
    return f
```
