"""X buzz: score-only, neutral on missing/stale/broken file."""
import json, time
import memebot

def _w(tmp_path, d):
    p = tmp_path / "x.json"; p.write_text(json.dumps(d)); return str(p)

def test_x_buzz_adj(tmp_path):
    now = time.time()
    good = {"m": {"authors": 20, "shill_ratio": 0.1, "score": 80, "posts_1h": 25, "ts": now}}
    assert memebot.x_buzz_adj("m", _w(tmp_path, good), now=now)[0] == 6.0
    shill = {"m": {"authors": 3, "shill_ratio": 0.6, "score": 30, "posts_1h": 20, "ts": now}}
    assert memebot.x_buzz_adj("m", _w(tmp_path, shill), now=now)[0] == -3.0
    stale = {"m": dict(good["m"], ts=now - 46*60)}
    assert memebot.x_buzz_adj("m", _w(tmp_path, stale), now=now)[0] == 0.0
    assert memebot.x_buzz_adj("m", str(tmp_path / "missing.json"))[0] == 0.0
    bad = tmp_path / "bad.json"; bad.write_text("{not json")
    assert memebot.x_buzz_adj("m", str(bad))[0] == 0.0
    assert memebot.x_buzz_adj("other", _w(tmp_path, good), now=now)[0] == 0.0
