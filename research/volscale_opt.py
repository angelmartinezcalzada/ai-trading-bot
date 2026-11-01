"""v3.1 exits scaled per coin by its own 1m ATR% relative to the universe median (calibrated on train only)."""
import sys, statistics as st; sys.argv = sys.argv[:1] + ['0']; sys.path.insert(0, 'research')
exec(open('research/levels_opt.py').read().split("if __name__")[0])
for s in S: s['atrp'] = (atr(s['pre']) or 0) / s['post'][0][1]
MED = st.median(s['atrp'] for s in S[:cut])        # train-only reference
def vs(s, P):
    m = min(P['hi'], max(P['lo'], (s['atrp']/MED)**P['pw'])); b = s['post']; e = b[0][1]; rt = s['rt']
    SP, TP, ACT, TR = .10*m, .25*m, .20*m, .10*m; stop = max(SP, min(SP*1.5, SP+rt)); size = min(CAP, RISK/stop)
    half = 1; real = 0; best = e; part = False
    for t,o,h,l,cl,v in b:
        if not part and h >= e*(1+TP): real += .5*TP; half = .5; part = True; stop = 0.0
        best = max(best, h)
        if l <= e*(1-stop): return size*(real+half*(-stop)-rt)
        tr = TR*1.2 if part else TR
        if best >= e*(1+ACT) and l <= best*(1-tr): return size*(real+half*(best*(1-tr)/e-1)-rt)
        if t-b[0][0] > 12*3600: return size*(real+half*(cl/e-1)-rt)
    return size*(real+half*(b[-1][4]/e-1)-rt)
print('MED atr% 1m', round(100*MED, 3), 'v3.1 TR', ev(S[:cut], v31), 'TE', ev(S[cut:], v31))
R = []
for pw in (0.25, 0.5, 0.75, 1.0):
    for lo, hi in ((0.5, 2.0), (0.7, 1.5), (0.4, 3.0)):
        P = dict(pw=pw, lo=lo, hi=hi); R.append((ev(S[:cut], lambda s: vs(s, P)), ev(S[cut:], lambda s: vs(s, P)), P))
R.sort(key=lambda x: -x[0]['avg_bp'])
for a, b, P in R[:5]: print(P, 'TR', a, 'TE', b)
import json; json.dump(dict(med_atrp=MED, best=R[0][2], train=R[0][0], test=R[0][1], v31_train=ev(S[:cut], v31), v31_test=ev(S[cut:], v31)), open('research/volscale_opt.json', 'w'), indent=1)
