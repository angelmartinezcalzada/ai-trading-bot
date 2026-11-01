import os, json, csv, time, re, collections
from flask import jsonify, Response
D = os.path.dirname(os.path.abspath(__file__))
P = lambda f: os.path.join(D, f)
_hist = collections.defaultdict(list)  # mint -> [(t, mark)]
def J(f, d=None):
    try: return json.load(open(P(f)))
    except Exception: return d
def tail(f, n):
    try:
        with open(P(f), "rb") as h:
            h.seek(0, 2); s = h.tell(); h.seek(max(0, s-300_000)); return h.read().decode(errors="replace").splitlines()[-n:]
    except FileNotFoundError: return []
def rows(f, n):
    L = tail(f, n+1)
    try: hdr = open(P(f)).readline().strip().split(",")
    except Exception: return []
    out = []
    for r in csv.reader([l for l in L if not l.startswith(hdr[0]+",")]):
        if len(r) >= len(hdr): out.append(dict(zip(hdr, r[:len(hdr)-1] + [",".join(r[len(hdr)-1:])] if len(r) > len(hdr) else r)))
    return out
def api():
    st = J("status_solana.json", {}) or {}
    raw = (J("state_solana_live.json", {}) or {}).get("pos", {})
    eq = [(int(a), float(b)) for a, b in (l.split(",")[:2] for l in tail("equity_solana.csv", 3000) if l[:1].isdigit())]
    cut = time.time() - 36*3600
    eq = [e for e in eq if e[0] >= cut and e[1] < 500]
    pos = []
    for p in st.get("positions", []) or []:
        m = p.get("mint"); h = _hist[m]
        if not h or h[-1][0] < st.get("ts", 0): h.append((st.get("ts", time.time()), p.get("mark")))
        del h[:-400]
        best = (raw.get(m) or {}).get("best") or max([x[1] for x in h if x[1]] + [p.get("entry", 0)])
        pos.append({k: p.get(k) for k in ("sym", "entry", "mark", "pnl", "pnl_pct", "age_min", "cost", "strategy")} |
                   {"peak": best, "trail": best*0.88, "hard": p.get("entry", 0)*0.94, "hist": h})
    tr = rows("trades_solana_live.csv", 60)
    feed = [{"t": r["time"], "sym": r["symbol"].strip(), "side": r["side"], "price": r["price"], "pnl": float(r.get("pnl") or 0),
             "reason": re.sub(r" tx=\S+", "", r.get("reason", ""))[:90]} for r in tr]
    scan = an = ex = None; events = []
    for l in tail("bot_solana.log", 600):
        c = re.sub(r" tx=\S+", "", l[11:19] + " " + l.split("] ", 1)[-1].split(" INFO ", 1)[-1])[:220]
        if " SCAN " in l: scan = c
        if "prefilter" in l: an = c
        if re.search(r"BUY|SELL|EXIT|HALT|SWITCH|STOP", l): events.append(c); ex = c if "BUY" in l else ex
    ins = J("insider_status.json", {}) or {}
    conv = sorted((ins.get("conv") or {}).items(), key=lambda kv: -kv[1].get("score", 0))[:3]
    ct = rows("trades_solana_copy_paper.csv", 200); ctc = [float(r["pnl"] or 0) for r in ct if r["side"] != "BUY"]
    cps = J("state/copytrade_paper.json", {}) or {}
    sig = (st.get("signals") or [])[-3:]
    return {"ts": st.get("ts"), "equity": st.get("equity"), "cash": st.get("cash"), "day_pct": st.get("day_pnl_pct"),
            "day_usd": (st.get("equity") or 0) - (st.get("equity") or 0)/(1+(st.get("day_pnl_pct") or 0)/100),
            "halted": st.get("halted"), "paused": st.get("paused"), "eqc": eq[::max(1, len(eq)//300)], "positions": pos,
            "feed": feed[::-1][:40], "events": events[-15:][::-1],
            "agents": {"scanner": scan, "analyst": an, "signals": [f"{s['sym']}: {(s.get('mtf') or 'ok')[:80]}" for s in sig],
                       "executor": ex, "size": "8% del saldo", "risk": f"{len(pos)} posiciones vigiladas · stop -6% | trail 12%",
                       "insider": {"tracked": ins.get("tracked"), "cycle_s": ins.get("cycle_s"), "top": [{"mint": k[:6]+"…", **v} for k, v in conv]},
                       "copy": {"closes": len(ctc), "pnl": round(sum(ctc), 2), "wins": sum(1 for x in ctc if x > 0), "open": len(cps.get("pos") or {})}}}
PAGE = r"""<!doctype html><html lang=es><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>Bot en directo</title>
<style>body{margin:0;background:#07090f;color:#e8ecf5;font-family:system-ui,-apple-system;padding:14px;max-width:760px;margin:auto}
.big{font-size:44px;font-weight:800}.g{color:#22e39a}.r{color:#ff5470}.m{color:#8b93a7;font-size:12px}
.card{background:#111522;border:1px solid #1d2336;border-radius:14px;padding:12px;margin:10px 0}
.ag{display:flex;gap:10px;overflow-x:auto;scroll-snap-type:x mandatory}.ag .card{min-width:230px;scroll-snap-align:start;font-size:13px}
.ag h4{margin:0 0 6px}.dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:#22e39a;margin-right:6px;animation:p 1.4s infinite}
@keyframes p{50%{opacity:.25}}#feed div{padding:6px 0;border-bottom:1px solid #1a1f30;font-size:13px}
#toast{position:fixed;top:16px;left:50%;transform:translateX(-50%);background:#22e39a;color:#000;padding:12px 18px;border-radius:12px;font-weight:700;display:none;z-index:9}
canvas{width:100%}</style><div id=toast></div>
<div class=m><span class=dot></span>EN DIRECTO · Solana real · <span id=upd></span></div>
<div class=big id=eq>…</div><div id=day></div><canvas id=ch height=150></canvas>
<h3>Agentes</h3><div class=ag id=ag></div><h3>Posiciones abiertas</h3><div id=pos></div>
<h3>Actividad</h3><div class=card id=feed></div><h3>Eventos</h3><div class="card m" id=ev></div>
<script>
let seen=null;const $=i=>document.getElementById(i),f=(x,d=2)=>x==null?'—':(+x).toFixed(d);
function line(c,pts,lines){const x=c.getContext('2d'),W=c.width=c.clientWidth*2,H=c.height=c.clientHeight*2||300;x.clearRect(0,0,W,H);
 if(pts.length<2){x.fillStyle='#8b93a7';x.font='24px system-ui';x.fillText('esperando datos…',20,H/2);return}
 let v=pts.map(p=>p[1]).concat(lines.map(l=>l.v)),lo=Math.min(...v),hi=Math.max(...v);if(hi==lo){hi+=1e-9;lo-=1e-9}const pad=(hi-lo)*.1;lo-=pad;hi+=pad;
 const t0=pts[0][0],t1=pts[pts.length-1][0]||t0+1,X=t=>(t-t0)/(t1-t0||1)*W,Y=y=>H-(y-lo)/(hi-lo)*H;
 for(const l of lines){x.strokeStyle=l.c;x.setLineDash(l.d||[]);x.lineWidth=2;x.beginPath();x.moveTo(0,Y(l.v));x.lineTo(W,Y(l.v));x.stroke();x.setLineDash([]);x.fillStyle=l.c;x.font='20px system-ui';x.fillText(l.t,6,Y(l.v)-6)}
 const up=pts[pts.length-1][1]>=pts[0][1];x.strokeStyle=up?'#22e39a':'#ff5470';x.lineWidth=4;x.beginPath();pts.forEach((p,i)=>i?x.lineTo(X(p[0]),Y(p[1])):x.moveTo(X(p[0]),Y(p[1])));x.stroke();
 x.lineTo(W,H);x.lineTo(0,H);x.fillStyle=up?'rgba(34,227,154,.08)':'rgba(255,84,112,.08)';x.fill()}
function toast(s){const t=$('toast');t.textContent=s;t.style.display='block';confetti();setTimeout(()=>t.style.display='none',4000)}
function confetti(){for(let i=0;i<60;i++){const d=document.createElement('div');d.style.cssText=`position:fixed;top:-10px;left:${Math.random()*100}vw;width:8px;height:12px;background:hsl(${Math.random()*360},90%,60%);z-index:8;transition:transform 2.5s ease-in,opacity 2.5s`;document.body.appendChild(d);requestAnimationFrame(()=>{d.style.transform=`translateY(105vh) rotate(${Math.random()*720}deg)`;d.style.opacity=0});setTimeout(()=>d.remove(),2600)}}
async function tick(){try{const r=await fetch('/api/live');if(r.status==401){location='/login';return}const d=await r.json(),a=d.agents;
 $('eq').textContent=f(d.equity)+' $';const c=d.day_usd>=0?'g':'r';$('day').innerHTML=`<span class=${c}>${d.day_usd>=0?'+':''}${f(d.day_usd)} $ (${f(d.day_pct)}%) hoy</span> <span class=m>${d.halted?'⛔ PARADO':d.paused?'⏸ pausa':''}</span>`;
 $('upd').textContent=d.ts?new Date(d.ts*1000).toLocaleTimeString('es-ES'):'';line($('ch'),d.eqc,[]);
 const ins=a.insider;$('ag').innerHTML=[
 ['🔎 Scanner',a.scanner||'—'],['🧠 Analista',(a.analyst||'—')+'<br><span class=m>'+a.signals.join('<br>')+'</span>'],
 ['⚡ Ejecutor',(a.executor||'sin compras recientes')+'<br><span class=m>tamaño: '+a.size+'</span>'],['🛡️ Riesgo',a.risk],
 ['🕵️ Insiders',`${ins.tracked} wallets · ciclo ${Math.round(ins.cycle_s||0)}s<br><span class=m>${ins.top.map(t=>t.mint+' elite '+t.elite+' · score '+t.score).join('<br>')}</span>`],
 ['📋 Copytrade (simulación)',`${a.copy.closes} cierres · ${a.copy.wins} ganados · <b class=${a.copy.pnl>=0?'g':'r'}>${f(a.copy.pnl)} $</b> · ${a.copy.open} abiertas`]
 ].map(([h,b])=>`<div class=card><h4><span class=dot></span>${h}</h4>${b}</div>`).join('');
 $('pos').innerHTML=d.positions.length?d.positions.map((p,i)=>`<div class=card><b>${p.sym}</b> <span class=${p.pnl>=0?'g':'r'}>${f(p.pnl,3)} $ (${f(p.pnl_pct)}%)</span> <span class=m>${f(p.age_min,0)} min</span><canvas id=pc${i} height=110></canvas></div>`).join(''):'<div class="card m">Sin posiciones abiertas — todo en efectivo.</div>';
 d.positions.forEach((p,i)=>line($('pc'+i),p.hist,[{v:p.entry,c:'#8b93a7',t:'entrada'},{v:p.trail,c:'#ff5470',d:[8,8],t:'trailing -12%'},{v:p.hard,c:'#ff9f43',d:[3,6],t:'stop -6%'}]));
 $('feed').innerHTML=d.feed.map(x=>{const c=x.side=='BUY'?'':x.pnl>0?'g':'r';return `<div class=${c}><b>${x.side=='BUY'?'🟢 COMPRA':x.pnl>0?'💰 VENTA':'🔻 VENTA'} ${x.sym}</b> ${x.side=='BUY'?'':(x.pnl>0?'+':'')+f(x.pnl,3)+' $'} <span class=m>${x.t.slice(5,16).replace('T',' ')} · ${x.reason}</span></div>`}).join('');
 $('ev').innerHTML=d.events.join('<br>');
 const wins=d.feed.filter(x=>x.side=='SELL'&&x.pnl>0).map(x=>x.t+x.sym);
 if(seen){const n=d.feed.find(x=>x.side=='SELL'&&x.pnl>0&&!seen.has(x.t+x.sym));if(n)toast(`💰 ${n.sym} +${f(n.pnl,3)} $`)}seen=new Set(wins);
}catch(e){}}tick();setInterval(tick,1500);
</script></html>"""
def register(app):
    app.add_url_rule("/live", "live", lambda: Response(PAGE, mimetype="text/html"))
    app.add_url_rule("/api/live", "api_live", lambda: jsonify(api()))
