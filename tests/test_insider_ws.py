"""insider_ws: wallet selection, JSON-RPC message handling, the queue protocol insider.live() drains, and the health flag."""
import json, os, time
import insider_ws as iw


def test_pick_wallets_elite_first_by_score_and_capped():
    W = {"wallets": {"a": {"tier": "good", "sc": 9}, "b": {"tier": "elite", "sc": 1}, "c": {"tier": "elite", "sc": 5}, "d": {"tier": "watch", "sc": 99}, "e": "junk"}}
    assert iw.pick_wallets(W) == ["c", "b", "a"] and iw.pick_wallets(W, max_wallets=2) == ["c", "b"] and iw.pick_wallets({}) == []


def test_subscribe_and_notification_round_trip():
    pending, subs = {1: "W1", 2: "W2"}, {}
    assert iw.on_message(json.dumps({"jsonrpc": "2.0", "id": 1, "result": 555}), pending, subs) == ("sub", 1, 555) and subs == {555: "W1"} and pending == {2: "W2"}
    note = {"jsonrpc": "2.0", "method": "logsNotification", "params": {"subscription": 555, "result": {"context": {"slot": 1}, "value": {"signature": "SIG1", "err": None, "logs": []}}}}
    assert iw.on_message(json.dumps(note), pending, subs) == ("event", "W1", "SIG1")
    note["params"]["result"]["value"]["err"] = {"InstructionError": [0, "x"]}
    assert iw.on_message(json.dumps(note), pending, subs) is None                       # failed tx: ignored
    note["params"]["result"]["value"]["err"] = None; note["params"]["subscription"] = 999
    assert iw.on_message(json.dumps(note), pending, subs) is None                       # unknown subscription
    assert iw.on_message("not json", pending, subs) is None and iw.on_message(json.dumps({"id": 7, "result": 1}), pending, subs) is None
    m = iw.subscribe_msg(3, "W3"); assert m["method"] == "logsSubscribe" and m["params"][0] == {"mentions": ["W3"]} and m["params"][1]["commitment"] == "confirmed"


def test_queue_drain_is_newest_first_deduped_and_truncates(tmp_path):
    q = str(tmp_path / "q.jsonl")
    assert iw.drain(q) == {}
    iw.enqueue(q, "W1", "s1", 1); iw.enqueue(q, "W1", "s2", 2); iw.enqueue(q, "W2", "s3", 3); iw.enqueue(q, "W1", "s2", 4)
    open(q, "a").write("garbage\n")
    assert iw.drain(q) == {"W1": ["s2", "s1"], "W2": ["s3"]}
    assert os.path.getsize(q) == 0 and iw.drain(q) == {}                                   # consumed


def test_healthy_requires_recent_connected_status(tmp_path, monkeypatch):
    p = str(tmp_path / "st.json"); now = time.time()
    assert iw.healthy(p) is False
    json.dump({"ts": now - 10, "state": "connected"}, open(p, "w")); assert iw.healthy(p, now) is True
    json.dump({"ts": now - 500, "state": "connected"}, open(p, "w")); assert iw.healthy(p, now) is False
    json.dump({"ts": now - 10, "state": "error: boom"}, open(p, "w")); assert iw.healthy(p, now) is False


def test_pick_wallets_prefers_rank_doc_and_health_passthrough(tmp_path):
    import sys, types
    W = {"wallets": {"a": {"tier": "good", "sc": 9}, "b": {"tier": "elite", "sc": 1}, "c": {"tier": "elite", "sc": 5}, "d": {"tier": "watch", "sc": 99}}}
    rw = lambda tier, rel, bot=False: {"tier": tier, "rel": rel, "bot": bot}
    R = {"t": time.time(), "code": "insider_rank/1", "wallets": {"a": rw("elite", 0.9), "b": rw("elite", 0.8, True), "c": rw("good", 0.7), "d": rw("good", 0.6), "z": rw("elite", 0.99)}, "top": ["z", "b", "a"]}
    assert iw.rank_eligible(R, W["wallets"]) == ["a", "c", "d"]                           # z unknown to mining and b (bot): never; c, d appended by rel; tier from the rank
    assert iw.pick_wallets(W, R=R) == ["a", "c", "d"] and iw.pick_wallets(W, max_wallets=2, R=R) == ["a", "c"] and iw.pick_wallets(W, R={"wallets": {}}) == []
    assert iw.pick_wallets(W, R={"nope": 1}) == ["c", "b", "a"]                           # not a rank doc: old ordering
    p = str(tmp_path / "st.json"); now = time.time(); assert iw.health(p) is None
    json.dump({"ts": now - 10, "state": "connected", "subs": 5, "events": 2, "ws": "wss://x/?api-key=S"}, open(p, "w"))
    h = iw.health(p, now); assert h["ok"] is True and h["subs"] == 5 and h["events"] == 2 and h["age_s"] == 10 and "ws" not in h and iw.healthy(p, now) is True
    json.dump({"ts": now - 10, "state": "error: boom"}, open(p, "w")); assert iw.health(p, now)["ok"] is False and iw.healthy(p, now) is False
    # rank_load: injected module, stale doc, None, exception, absent module -> old ordering
    R0 = {"t": now, "wallets": {}}
    for mod, exp in ((types.SimpleNamespace(load=lambda root=".": R0), R0), (types.SimpleNamespace(load=lambda root=".": dict(R0, t=now - 3 * 3600)), None),
                     (types.SimpleNamespace(load=lambda root=".": None), None), (types.SimpleNamespace(load=lambda root=".": 1 / 0), None), (None, None)):
        sys.modules["insider_rank"] = mod
        try: assert iw.rank_load(now=now) is exp
        finally: sys.modules.pop("insider_rank", None)
