"""Purged walk-forward: current Brain (Beta-shrunk signal weights, log-odds) vs logistic regression vs gradient boosting.
Label: candidate's realised return with live exit rules on 1m paths > 0."""
import json, math, datetime as dt, numpy as np, sys
sys.path.insert(0, '.'); import brain
from sklearn.linear_model import LogisticRegression; from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.preprocessing import StandardScaler; from sklearn.pipeline import make_pipeline; from sklearn.metrics import roc_auc_score, brier_score_loss
c = json.load(open('config.json'))['exchanges']['solana']; P = json.load(open('research/meme_paths.json'))
def sim(b, rt):
    e=b[0][1]; stop=max(c['stop_pct'],min(c['max_stop_pct'],c['stop_pct']+rt)); half=1;real=0;best=e;part=False
    for t,o,h,l,cl,v in b:
        if not part and h>=e*(1+c['partial_tp_pct']): real+=c['partial_tp_frac']*c['partial_tp_pct']; half-=c['partial_tp_frac']; part=True; stop=0.0
        best=max(best,h)
        if l<=e*(1-stop): return real+half*(-stop)-rt, t
        tr=c['runner_trail_pct'] if part else c['trail_pct']
        if best>=e*(1+c['trail_activate_pct']) and l<=best*(1-tr): return real+half*(best*(1-tr)/e-1)-rt, t
        if t-b[0][0]>c['max_hold_hours']*3600: return real+half*(cl/e-1)-rt, t
    return None if b[-1][0]-b[0][0] < 3*3600 else (real+half*(b[-1][4]/e-1)-rt, b[-1][0])   # unresolved paths <3h dropped
NEWS = [json.loads(l) for l in open('news.jsonl')] if __import__('os').path.exists('news.jsonl') else []
def news_feat(t):
    rec=[n for n in NEWS if 0<=t-n['ts']<6*3600]; w=sum(n['imp'] for n in rec)
    return (sum(n['sent']*n['imp'] for n in rec)/w if w else 0.0, sum(1 for n in rec if n['imp']>=3 and n['sent']<0 and n['macro']))
F = ['liq','vol_liq','h1','m5','age_h','holder_g','socials','top10','rt','score','hour','buys_ratio','heat_hot','news_sent','news_neg3']
EX=[];X=[];Y=[];R=[];T=[];SIG=[];last={}
for l in open('candidates_solana.jsonl'):
    r=json.loads(l)
    if r.get('pair') not in P or r.get('score') is None or (r.get('liq') or 0)<c['min_liquidity_usd']: continue
    if any(f.split(':')[0] not in ('score','top10','no_momentum','brain_ev<=0','news_negative') for f in r['fail']): continue
    t=dt.datetime.fromisoformat(r['ts']).timestamp()
    if t-last.get(r['pair'],0)<600: continue
    b=[x for x in P[r['pair']]['bars'] if x[0]>=t]
    if len(b)<10 or b[0][0]-t>300: continue
    rt=(r.get('roundtrip_loss_pct') or 3.0)/100; y=sim(b,rt)
    if y is None: continue
    y,tx=y; EX.append(tx)
    last[r['pair']]=t; p=r.get('parts') or {}
    try: bb,ss=[float(x) for x in str(p.get('b_s','1/1')).split('/')]; br=bb/max(1,bb+ss)
    except Exception: br=.5
    ns=news_feat(t)
    X.append([math.log1p(r['liq']),p.get('vol_liq') or 0,p.get('h1') or 0,p.get('m5') or 0,min(p.get('age_h') or 99,500),p.get('holder_g') or 0,p.get('socials') or 0,
              (r.get('rug') or {}).get('top10') or 0,rt*100,r['score'],dt.datetime.fromtimestamp(t).hour,br,1 if r.get('heat')=='hot' else 0,ns[0],ns[1]])
    Y.append(int(y>0)); R.append(y); T.append(t); SIG.append(brain.signals(r) or {})
X=np.array(X,float);Y=np.array(Y);R=np.array(R);T=np.array(T); EX=np.array(EX); n=len(Y)
print(f'muestras {n}, positivos {Y.mean():.2f}, media ret {100*R.mean():.2f}%, ventana {(T.max()-T.min())/3600:.1f}h')
def brain_fit(idx):
    base=Y[idx].mean(); W={}
    keys={k for i in idx for k in SIG[i]}
    for k in keys:
        on=[Y[i] for i in idx if SIG[i].get(k)]; off=[Y[i] for i in idx if not SIG[i].get(k)]
        W[k]=((sum(on)+K*base)/(len(on)+K),(sum(off)+K*base)/(len(off)+K))
    def pred(i):
        z=brain.lo(base)
        for k,(pon,poff) in W.items(): z+=brain.DAMP*(brain.lo(pon if SIG[i].get(k) else poff)-brain.lo(base))
        return brain.sg(z)
    return pred
K=brain.K
models={'logit':lambda: make_pipeline(StandardScaler(),LogisticRegression(C=0.3,max_iter=500)),
        'gbm':lambda: HistGradientBoostingClassifier(max_depth=2,max_iter=60,learning_rate=0.05,min_samples_leaf=10,l2_regularization=1.0)}
o=np.argsort(T); folds=3; gap=2*3600; out={k:([],[],[]) for k in ['brain','logit','gbm','score']}
for f in range(1,folds+1):
    te=o[int(n*f/(folds+1)):int(n*(f+1)/(folds+1))]; t0=T[te].min(); tr=o[EX[o]<t0]      # purge: train ends 2h before test (max label horizon overlap)
    if len(tr)<20 or len(set(Y[tr]))<2: continue
    bp=brain_fit(tr); out['brain'][0].extend(Y[te]); out['brain'][1].extend([bp(i) for i in te]); out['brain'][2].extend(R[te])
    out['score'][0].extend(Y[te]); out['score'][1].extend(X[te,9]/100); out['score'][2].extend(R[te])
    for k,mk in models.items():
        m=mk().fit(X[tr],Y[tr]); out[k][0].extend(Y[te]); out[k][1].extend(m.predict_proba(X[te])[:,1]); out[k][2].extend(R[te])
res={}
for k,(y,p,r) in out.items():
    y,p,r=map(np.array,(y,p,r))
    if len(y)<10 or len(set(y))<2: continue
    sel=p>=np.median(p)
    res[k]=dict(n=len(y),auc=round(roc_auc_score(y,p),3),brier=round(brier_score_loss(y,np.clip(p,0,1)),3) if k!='score' else None,
                ret_top_half=round(100*r[sel].mean(),2),ret_all=round(100*r.mean(),2))
    print(k,res[k])
json.dump(dict(n=n,features=F,oos=res),open('research/model_cmp.json','w'),indent=1)
