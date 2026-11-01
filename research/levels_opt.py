"""Walk-forward: v3.1 fixed exits vs per-coin ATR/structure levels (+ entry pullback/breakout wait). Equity-normalised: both risk 0.5% of equity per trade."""
import json, itertools, datetime as dt, statistics as st, sys
sys.path.insert(0, 'research'); from levels import levels, atr
R = [json.loads(l) for l in open('candidates_solana.jsonl')]; PTH = json.load(open('research/meme_paths.json'))
RISK, CAP = 0.005, 0.08
MINS = int(sys.argv[1]) if len(sys.argv) > 1 else 45
S = []; last = {}
for r in R:
    if r.get('pair') not in PTH or r.get('score') is None or (r.get('liq') or 0) < 50000: continue
    if any(f.split(':')[0] not in ('score','top10','liq_pull','sell_spike','holders','socials','no_momentum','brain_ev<=0','news_negative','news_risk_off') for f in r['fail']): continue
    if r['score'] < MINS: continue
    t = dt.datetime.fromisoformat(r['ts']).timestamp()
    if t-last.get(r['pair'], 0) < 1200: continue
    B = PTH[r['pair']]['bars']; pre = [x for x in B if x[0] < t]; post = [x for x in B if x[0] >= t]
    if len(pre) < 40 or len(post) < 30 or post[0][0]-t > 300: continue
    last[r['pair']] = t; S.append(dict(t=t, pre=pre[-120:], post=post, rt=(r.get('roundtrip_loss_pct') or 3.0)/100, sym=r['sym']))
S.sort(key=lambda s: s['t']); n = len(S); cut = int(n*.6)
def v31(s):
    b = s['post']; e = b[0][1]; rt = s['rt']; stop = max(.10, min(.15, .10+rt)); half = 1; real = 0; best = e; part = False
    for t,o,h,l,cl,v in b:
        if not part and h >= e*1.25: real += .5*.25; half = .5; part = True; stop = 0.0
        best = max(best, h)
        if l <= e*(1-stop): return 0.05*(real+half*(-stop)-rt)
        tr = .12 if part else .10
        if best >= e*1.20 and l <= best*(1-tr): return 0.05*(real+half*(best*(1-tr)/e-1)-rt)
        if t-b[0][0] > 12*3600: return 0.05*(real+half*(cl/e-1)-rt)
    return 0.05*(real+half*(b[-1][4]/e-1)-rt)
def dyn(s, P):
    pre, post, rt = s['pre'], s['post'], s['rt']; e0 = post[0][1]; a0 = atr(pre) or e0*.01
    i0 = 0
    if P['entry'] == 'pb':                                  # limit at pullback toward support within 20 min
        lim = e0 - P['kpb']*a0; i0 = next((i for i, x in enumerate(post[:20]) if x[3] <= lim), None)
        if i0 is None: return None
        e = min(lim, post[i0][1])
    elif P['entry'] == 'bo':                                # breakout confirmation: close above 15-bar high
        hh = max(x[2] for x in pre[-15:]); i0 = next((i for i, x in enumerate(post[:20]) if x[4] > hh), None)
        if i0 is None: return None
        i0 += 1
        if i0 >= len(post): return None
        e = post[i0][1]
    else: e = e0
    hist = pre + post[:i0]; L = levels(hist, e, P, rt); stop = L['stop']; size = min(CAP, RISK/L['dist'])
    half = 1; real = 0; best = e; part = False; win = hist[-30:]
    for j, x in enumerate(post[i0:]):
        t, o, h, l, cl, v = x; win = (win + [x])[-31:]; a = atr(win) or L['atr']     # live ATR update
        if not part and h >= L['tp1']: real += .5*(L['tp1']/e-1); half = .5; part = True; stop = max(stop, e)
        best = max(best, h)
        trail = best - (P['ktr']*(1.5 if part else 1))*a
        if part or best >= e + P['ktp']*0.6*L['atr']: stop = max(stop, trail)
        if l <= stop: return size*(real + half*(stop/e-1) - rt)
        if P['decay'] and j >= 60 and not part and cl < e + 0.5*L['atr'] and cl < win[-16][4]: return size*(real + half*(cl/e-1) - rt)
        if t-post[i0][0] > 12*3600: return size*(real + half*(cl/e-1) - rt)
    return size*(real + half*(post[-1][4]/e-1) - rt)
def ev(ss, f):
    r = [x for x in (f(s) for s in ss) if x is not None]
    return dict(n=len(r), avg_bp=round(1e4*st.mean(r), 1) if r else None, sum_pct=round(100*sum(r), 2), win=round(100*sum(x > 0 for x in r)/len(r)) if r else None)
G = [dict(ks=a, ktp=b, ktr=c, kpb=d, entry=e, decay=f) for a, b, c, d, e, f in itertools.product([2, 3, 4, 6], [4, 6, 10, 15], [2, 3, 5, 8], [1, 2], ['mkt', 'pb', 'bo'], [0, 1])]
G = [g for g in G if g['entry'] == 'pb' or g['kpb'] == 1]
if __name__ == '__main__':
    print(f'muestras {n} (train {cut}, test {n-cut})')
    print('v3.1  train', ev(S[:cut], v31), 'test', ev(S[cut:], v31))
    tr = sorted(((ev(S[:cut], lambda s, g=g: dyn(s, g)), g) for g in G), key=lambda x: -(x[0]['sum_pct']))
    tr = [x for x in tr if x[0]['n'] >= max(8, cut//3)]
    for m, g in tr[:6]: print(g, 'train', m, 'test', ev(S[cut:], lambda s, g=g: dyn(s, g)))
    best = tr[0][1]; json.dump(dict(best=best, n=n, train=tr[0][0], test=ev(S[cut:], lambda s: dyn(s, best)), v31_test=ev(S[cut:], v31), v31_train=ev(S[:cut], v31)), open('research/levels_opt.json', 'w'), indent=1)
