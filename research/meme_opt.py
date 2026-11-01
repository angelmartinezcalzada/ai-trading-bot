"""Walk-forward grid over memebot entry/exit params on real 1m paths. Train = first 60% of sightings by time, test = rest."""
import json, itertools, datetime as dt, statistics as st
R=[json.loads(l) for l in open('candidates_solana.jsonl')]; P=json.load(open('research/meme_paths.json'))
S=[]; last={}
for r in R:
    if not r.get('pair') in P or r.get('score') is None: continue
    if any(f.split(':')[0] not in ('score','top10') for f in r['fail']): continue
    t=dt.datetime.fromisoformat(r['ts']).timestamp()
    if t-last.get(r['pair'],0)<3600: continue
    bars=[b for b in P[r['pair']]['bars'] if b[0]>=t]
    if len(bars)<20 or bars[0][0]-t>300: continue
    last[r['pair']]=t; S.append(dict(t=t,score=r['score'],m5=r['parts'].get('m5') or 0,h1=r['parts'].get('h1') or 0,rt=r.get('roundtrip_loss_pct') or 3.0,bars=bars))
S.sort(key=lambda s:s['t']); n=len(S); cut=int(n*.6)
def sim(s,c):
    b=s['bars']; e=b[0][1]; rt=s['rt']/100; stop=max(c['stop'],min(c['stop']*2,c['stop']+rt)); half=1;real=0;best=e;part=False
    for t,o,h,l,cl,v in b:
        if not part and h>=e*1.25: real+=.5*.25; half=.5; part=True; stop=0.0
        best=max(best,h)
        if l<=e*(1-stop): return real+half*(-stop)-rt
        tr=.12 if part else c['trail']
        if best>=e*(1+c['act']) and l<=best*(1-tr): return real+half*(best*(1-tr)/e-1)-rt
        if t-b[0][0]>c['hold']*3600: return real+half*(cl/e-1)-rt
    return real+half*(b[-1][4]/e-1)-rt
def ok(s,c): return s['score']>=c['min'] and (not c['mom'] or (s['m5']>0 and s['h1']>0))
def ev(ss,c):
    r=[sim(s,c) for s in ss if ok(s,c)]
    return (len(r), round(100*st.mean(r),2) if r else None, round(100*sum(x>0 for x in r)/len(r)) if r else None)
G=[dict(min=m,mom=mo,stop=sp,trail=tr,act=a,hold=h) for m,mo,sp,tr,a,h in itertools.product([0,45,55,65],[0,1],[.06,.10,.15],[.06,.10],[.12,.20],[2,12])]
base=dict(min=45,mom=0,stop=.06,trail=.06,act=.12,hold=12)
print('samples',n,'train',cut)
print('BASE train',ev(S[:cut],base),'test',ev(S[cut:],base),'all',ev(S,base))
res=sorted(((ev(S[:cut],c),c) for c in G if ev(S[:cut],c)[0]>=6),key=lambda x:-(x[0][1]))
for tr,c in res[:8]: print(c,'train',tr,'test',ev(S[cut:],c))
print('--- robustez (todas las puntuaciones, min=0)')
for sp in (.06,.10,.15):
  for tr,a in ((.06,.12),(.10,.20),(.06,.20)):
    c=dict(min=0,mom=0,stop=sp,trail=tr,act=a,hold=12); print(sp,tr,a,'train',ev(S[:cut],c),'test',ev(S[cut:],c))
for mo in (0,1): c=dict(min=0,mom=mo,stop=.10,trail=.10,act=.20,hold=12); print('mom',mo,ev(S,c))
