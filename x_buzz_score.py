#!/usr/bin/env python3
"""Turns saved X search results into data/x_buzz.json.
usage: x_buzz_score.py pairs.json   where pairs.json = [{"sym":..,"mint":..,"file":"<saved search_posts_all result>"}]
Metrics over the last 60 min: posts_1h, authors (distinct), engagement (likes+reposts+replies+quotes),
shill_ratio 0-1 = max(repeat share 1-authors/posts, share of posts from accounts <30 days old, 0.6*share of 'VIP/telegram/DM' promo posts),
score 0-100 = organic reach (authors, engagement, volume) x (1 - shill_ratio)."""
import json, sys, math, re, datetime as dt, os
PROMO = re.compile(r"vip|telegram|t\.me/|dm me|send me a dm|join my|100x|1000x|next gem|calls? group|giveaway|express listing|listing", re.I)
def load(path):
    t = open(path, encoding="utf-8").read(); i = t.find("{"); j = t.rfind("}")
    return json.loads(t[i:j+1]) if i >= 0 else {}
def metrics(d, now, sym="", mint=""):
    users = {u["id"]: u for u in (d.get("includes") or {}).get("users", [])}
    posts = [p for p in d.get("data") or [] if (now-dt.datetime.fromisoformat(p["created_at"].replace("Z", "+00:00"))).total_seconds() <= 3600
             and ((mint and mint in p.get("text", "")) or (sym and re.search(r"\$" + re.escape(sym) + r"\b", p.get("text", ""), re.I)))]   # X search ignores '$': keep only posts that really name the coin
    n = len(posts); A = {p.get("author_id") for p in posts}
    if not n: return dict(posts_1h=0, authors=0, engagement=0, shill_ratio=0.0, score=0)
    eng = sum(sum((p.get("public_metrics") or {}).get(k, 0) for k in ("like_count", "retweet_count", "reply_count", "quote_count")) for p in posts)
    young = sum(1 for p in posts if (u := users.get(p.get("author_id"))) and u.get("created_at") and (now-dt.datetime.fromisoformat(u["created_at"].replace("Z", "+00:00"))).days < 30)/n
    promo = sum(1 for p in posts if PROMO.search(p.get("text", "")))/n
    shill = round(min(1.0, max(1-len(A)/n, young, 0.6*promo)), 2)
    base = min(60, 15*math.log1p(len(A))) + min(25, 5*math.log1p(eng)) + min(15, n/4)
    return dict(posts_1h=n, authors=len(A), engagement=eng, shill_ratio=shill, score=round(max(0, min(100, base*(1-shill)))), capped=len(d.get("data") or []) >= 25)
def main(pairs):
    now = dt.datetime.now(dt.timezone.utc); out = {}
    for r in json.load(open(pairs)):
        try: out[r["mint"]] = dict(sym=r["sym"], **metrics(load(r["file"]), now, r["sym"], r["mint"]), ts=int(now.timestamp()))
        except Exception as e: print("skip", r.get("sym"), e, file=sys.stderr)
    os.makedirs("data", exist_ok=True); tmp = "data/x_buzz.json.tmp"
    json.dump(out, open(tmp, "w"), indent=1); os.replace(tmp, "data/x_buzz.json")   # atomic: the bot never reads a half-written file
    for m, v in sorted(out.items(), key=lambda x: -x[1]["score"]): print(f"{v['sym']:<12} posts={v['posts_1h']:<3} authors={v['authors']:<3} eng={v['engagement']:<5} shill={v['shill_ratio']:.2f} score={v['score']}")
if __name__ == "__main__": main(sys.argv[1])
