"""AI-narrative pump anticipation + exhaustion scores (live). Price/volume parts are the ones validated in research/pump_study.py;
flow parts (buyers, buy/sell, liquidity add, trending, news) come from DexScreener/GeckoTerminal snapshots and are scored but logged as shadow."""
import re, time, json, numpy as np
AI_RE = re.compile(r"(?<![a-z])(ai|a\.i\.|gpt|agi|llm|agent|agents|neural|neuro|bot|robot|cyborg|sentient|brain|deepseek|grok|openai|claude|virtual|aixbt|machine|singularity|terminal|quant)(?![a-z])", re.I)
def is_ai(name, sym, desc="", tags=(), narr=()):
    txt = " ".join([name or "", sym or "", desc or "", " ".join(tags or [])])
    return bool(AI_RE.search(txt)) or any(n in ("ai", "agent", "gpt", "bot") for n in (narr or [])) or bool(re.search(r"AI$|^AI", (sym or "")))
def _f(bars):
    b = np.array(bars, float); t, o, h, l, c, v = b.T; n = len(c)
    pc = np.r_[c[0], c[:-1]]; tr = np.maximum(h, pc) - np.minimum(l, pc)
    m = lambda x, w: x[-w:].mean() if len(x) >= w else x.mean()
    d = np.diff(c[-15:]); up = np.maximum(d, 0).mean(); dn = np.maximum(-d, 0).mean(); rsi = 100 - 100/(1 + up/max(dn, 1e-18))
    d2 = np.diff(c[-45:-15]) if n > 46 else d; rsi_prev = 100 - 100/(1 + np.maximum(d2, 0).mean()/max(np.maximum(-d2, 0).mean(), 1e-18))
    ema = c[0]
    for x in c: ema = 2/51*x + (1-2/51)*ema
    return dict(c=c[-1], vol_acc=m(v, 5)/max(np.median(v[-120:]) if n > 20 else 1e-9, 1e-9) if np.median(v[-120:]) > 0 else m(v, 5)/max(m(v, 120), 1e-9),
                comp=m(tr[:-15], 15)/max(m(tr, 120), 1e-18) if n > 40 else 1.0, brk=c[-1] > h[-61:-1].max() if n > 61 else False,
                ret5=c[-1]/c[-6]-1 if n > 6 else 0, ret15=c[-1]/c[-16]-1 if n > 16 else 0, ret60=c[-1]/c[-61]-1 if n > 61 else 0,
                ext=(c[-1]-ema)/max(m(tr, 60), 1e-18), climax=m(v, 3)/max(v[-120:].max(), 1e-9), rsi=rsi,
                div=bool(c[-1] >= h[-31:-1].max() and rsi < rsi_prev - 10) if n > 46 else False, atr_pct=m(tr, 15)/c[-1])
def scores(bars, pair=None, trending=False, news_hits=0, ai_heat=False, G=None):
    """returns dict(pump 0-100, exh 0-100, parts, sig_pump, sig_exh). G = validated thresholds"""
    G = G or {}; F = _f(bars); pr = pair or {}
    tx = pr.get("txns") or {}; m5 = tx.get("m5") or {}; h1 = tx.get("h1") or {}
    b5, s5, b1, s1 = m5.get("buys", 0), m5.get("sells", 0), h1.get("buys", 0), h1.get("sells", 0)
    buy_acc = (b5*12)/max(b1, 1); bs5 = b5/max(1, s5); bs1 = b1/max(1, s1)
    vol = pr.get("volume") or {}; vacc_dx = (vol.get("m5", 0)*12)/max(vol.get("h1", 0), 1)
    P = dict(vol_acc=min(F["vol_acc"]/5, 1)*25, coil=max(0, 1-F["comp"])*15, breakout=10 if F["brk"] else 0, buy_acc=min(buy_acc/3, 1)*15,
             buy_sell=min(max(bs5-1, 0), 1)*10, trending=10 if trending else 0, news=min(news_hits, 2)*5, ai_heat=5 if ai_heat else 0)
    pump = sum(P.values())
    E = dict(climax=min(F["climax"], 1)*20, extension=min(max(F["ext"]-2, 0)/6, 1)*25, divergence=20 if F["div"] else 0,
             flip=15 if bs5 < 1 < bs1 else 0, slowing=10 if F["ret5"] < 0 < F["ret15"] else 0, parabolic=10 if F["ret60"] > 0.5 else 0)
    exh = sum(E.values())
    sig_pump = F["vol_acc"] >= G.get("va", 3) and F["comp"] <= G.get("cp", .8) and (F["brk"] or not G.get("brk", 1)) and F["ret5"] > 0 and F["ret60"] < G.get("maxrun", .5)
    sig_exh = F["ret60"] >= .25 and ((F["climax"] >= G.get("cl", .8) and F["ext"] >= G.get("ex", 5)) or F["div"] or (F["ret5"] < 0 < F["ret15"] and F["ext"] >= G.get("ex", 5)))
    return dict(pump=round(pump), exh=round(exh), pump_parts={k: round(v, 1) for k, v in P.items()}, exh_parts={k: round(v, 1) for k, v in E.items()},
                sig_pump=bool(sig_pump), sig_exh=bool(sig_exh), f={k: (round(float(v), 4) if not isinstance(v, (bool, np.bool_)) else bool(v)) for k, v in F.items()})
