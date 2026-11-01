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
