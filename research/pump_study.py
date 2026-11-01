"""Walk-forward study: AI-memecoin pump anticipation + exhaustion exits on real GeckoTerminal 1m OHLCV (research/ai_paths.json).
Only price/volume signals can be validated historically (no historical tx/holder/whale feeds) -> flow signals stay shadow."""
import json, numpy as np, itertools, sys
D = json.load(open('research/ai_paths.json')); RISK, CAP, RT = 0.005, 0.08, 0.025
def feats(b):
    b = np.array(b, float); t, o, h, l, c, v = b.T; n = len(c)
    pc = np.r_[c[0], c[:-1]]; tr = np.maximum(h, pc) - np.minimum(l, pc)
    def roll(x, w, f):
        out = np.full(n, np.nan)
        for i in range(w, n): out[i] = f(x[i-w:i])
        return out
    cs = lambda x, w: np.r_[np.full(w, np.nan), (np.cumsum(x)[w:] - np.cumsum(x)[:-w])] / w
    atr15, atr120 = cs(tr, 15), cs(tr, 120); vol5 = cs(v, 5); volb = cs(v, 120)
    hh60 = roll(h, 60, np.max); vmax120 = roll(v, 120, np.max)
    d = np.diff(c, prepend=c[0]); up = cs(np.maximum(d, 0), 14); dn = cs(np.maximum(-d, 0), 14); rsi = 100 - 100/(1 + up/np.maximum(dn, 1e-18))
    ema = np.zeros(n); a = 2/51; ema[0] = c[0]
    for i in range(1, n): ema[i] = a*c[i] + (1-a)*ema[i-1]
    r = lambda w: np.r_[np.full(w, np.nan), c[w:]/c[:-w]-1]
    F = dict(t=t, o=o, h=h, l=l, c=c, v=v, atr=atr15, vol_acc=vol5/np.maximum(volb, 1e-9), comp=atr15/np.maximum(atr120, 1e-18), brk=c > hh60,
             ret5=r(5), ret15=r(15), ret60=r(60), rsi=rsi, ext=(c-ema)/np.maximum(cs(tr, 60), 1e-18), climax=cs(v, 3)/np.maximum(vmax120, 1e-9))
    # rsi divergence: price at 30-bar high but rsi below its 30-bar max by >10
    F['div'] = np.r_[np.zeros(30, bool), [(c[i] >= h[i-30:i].max()) and (rsi[i] < np.nanmax(rsi[i-30:i]) - 10) for i in range(30, n)]]
    fh = np.full(n, np.nan); arg = np.full(n, np.nan); fl30 = np.full(n, np.nan); fh30 = np.full(n, np.nan)
    for i in range(n-60):
        w = h[i+1:i+61]; fh[i] = w.max()/c[i]-1; arg[i] = w.argmax()+1; fl30[i] = l[i+1:i+31].min()/c[i]-1; fh30[i] = h[i+1:i+31].max()/c[i]-1
    F.update(fwd_max60=fh, lead=arg, fwd_min30=fl30, fwd_max30=fh30); return F
P = {}
for k, v in D.items():
    if len(v['bars']) >= 400: P[k] = feats(v['bars'])
allt = np.sort(np.concatenate([f['t'] for f in P.values()])); CUT = allt[int(len(allt)*.6)]
print(f"pools {len(P)}, barras {len(allt)}, corte {CUT:.0f}")
def pump_sig(F, i, g): return F['vol_acc'][i] >= g['va'] and F['comp'][i-15] <= g['cp'] and (F['brk'][i] or not g['brk']) and F['ret5'][i] > 0 and F['ret60'][i] < g['maxrun']
def exh_sig(F, i, g): return F['ret60'][i] >= .25 and ((F['climax'][i] >= g['cl'] and F['ext'][i] >= g['ex']) or F['div'][i] or (F['ret5'][i] < 0 < F['ret15'][i] and F['ext'][i] >= g['ex']))
def pump_eval(g, test):
    hits = n = 0; leads = []; base = bn = 0
    for F in P.values():
        last = -999
        for i in range(140, len(F['c'])-60):
            if (F['t'][i] >= CUT) != test or np.isnan(F['fwd_max60'][i]): continue
            bn += 1; base += F['fwd_max60'][i] >= .30
            if i - last < 30 or not pump_sig(F, i, g): continue
            last = i; n += 1
            if F['fwd_max60'][i] >= .30: hits += 1; leads.append(F['lead'][i])
    return dict(n=n, hit=round(hits/max(1, n)*100, 1), base=round(base/max(1, bn)*100, 2), lead_min=round(float(np.median(leads)), 0) if leads else None)
def exh_eval(g, test):
    n = hits = 0; bn = base = 0
    for F in P.values():
        last = -999
        for i in range(140, len(F['c'])-60):
            if (F['t'][i] >= CUT) != test or F['ret60'][i] < .25 or np.isnan(F['fwd_min30'][i]): continue
            top = F['fwd_min30'][i] <= -.10 and F['fwd_max30'][i] < .10
            bn += 1; base += top
            if i - last < 15 or not exh_sig(F, i, g): continue
            last = i; n += 1; hits += top
    return dict(n=n, hit=round(hits/max(1, n)*100, 1), base=round(base/max(1, bn)*100, 1))
def trade(F, i, use_exh, ge, m=1.0):
    """enter next open; volscale exits (stop 10%m, 50% TP 25%m, trail 10%m from +20%m); optional exhaustion scale-out (sell 50% into strength)"""
    if i+1 >= len(F['c']): return None
    e = F['o'][i+1]; sp = .10*m + RT; size = min(CAP, RISK/sp); half = 1; real = 0; best = e; part = False; stop = sp
    for j in range(i+1, min(len(F['c']), i+1+720)):
        hi, lo, cl = F['h'][j], F['l'][j], F['c'][j]
        if not part and hi >= e*(1+.25*m): real += .5*.25*m; half = .5; part = True; stop = 0
        best = max(best, hi)
        if lo <= e*(1-stop): return size*(real + half*(-stop) - RT)
        if use_exh and cl > e*1.1 and exh_sig(F, j, ge):
            if not part: real += .5*(cl/e-1); half = .5; part = True; stop = 0
            else: return size*(real + half*(cl/e-1) - RT)
        tr = .12*m if part else .10*m
        if best >= e*(1+.20*m) and lo <= best*(1-tr): return size*(real + half*(best*(1-tr)/e-1) - RT)
    return size*(real + half*(F['c'][min(len(F['c'])-1, i+720)]/e-1) - RT)
def strat_eval(entry, test, use_exh, ge, gp=None):
    R = []
    for F in P.values():
        last = -999
        for i in range(140, len(F['c'])-1):
            if (F['t'][i] >= CUT) != test or i - last < 60: continue
            ok = pump_sig(F, i, gp) if entry == 'pump' else (F['ret60'][i] > 0 and F['ret5'][i] > 0 and F['vol_acc'][i] >= 1) if entry == 'momentum' else dip_sig(F, i)
            if not ok: continue
            last = i; r = trade(F, i, use_exh, ge)
            if r is not None: R.append(r)
    R = np.array(R); return dict(n=len(R), ev_bp=round(1e4*R.mean(), 1) if len(R) else None, win=round(100*(R > 0).mean()) if len(R) else None)
def dip_sig(F, i):
    """after a +30% move in 120m: 38-62% retrace that holds (no new low in 10 bars), falling volume, then green bar"""
    if i < 130: return False
    w0, w1 = i-120, i-10; lo = F['l'][w0:w1].min(); hi = F['h'][w0:w1].max()
    if hi/lo < 1.3 or F['h'][w0:w1].argmax() < F['l'][w0:w1].argmin(): return False
    fib38, fib62 = hi-(hi-lo)*.382, hi-(hi-lo)*.618; c = F['c'][i]
    return fib62 <= c <= fib38 and F['l'][i-10:i+1].min() >= fib62*0.99 and F['v'][i-10:i].mean() < F['v'][w1-20:w1].mean() and F['c'][i] > F['o'][i]
if __name__ == '__main__':
    GP = [dict(va=a, cp=b, brk=c, maxrun=d) for a, b, c, d in itertools.product([2, 3, 5], [.6, .8, 1.0], [0, 1], [.15, .5])]
    tr = sorted(((pump_eval(g, False), g) for g in GP), key=lambda x: -(x[0]['hit'] if x[0]['n'] >= 30 else -1))
    gp = tr[0][1]; print('PUMP best', gp, 'train', tr[0][0], 'test', pump_eval(gp, True))
    GE = [dict(cl=a, ex=b) for a, b in itertools.product([.5, .8, 1.0], [3, 5, 8])]
    te = sorted(((exh_eval(g, False), g) for g in GE), key=lambda x: -(x[0]['hit']-x[0]['base'] if x[0]['n'] >= 20 else -99))
    ge = te[0][1]; print('EXH best', ge, 'train', te[0][0], 'test', exh_eval(ge, True))
    out = dict(pump=dict(g=gp, train=tr[0][0], test=pump_eval(gp, True)), exh=dict(g=ge, train=te[0][0], test=exh_eval(ge, True)), ev={})
    for name, ent, ex in [('momentum (actual)', 'momentum', 0), ('momentum + salida agotamiento', 'momentum', 1), ('pump', 'pump', 0), ('pump + agotamiento', 'pump', 1), ('dip', 'dip', 0), ('dip + agotamiento', 'dip', 1)]:
        a = strat_eval(ent, False, ex, ge, gp); b = strat_eval(ent, True, ex, ge, gp); out['ev'][name] = dict(train=a, test=b); print(name, 'train', a, 'test', b)
    json.dump(out, open('research/pump_study.json', 'w'), indent=1, default=str)
