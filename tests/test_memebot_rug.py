"""RugCheck fetching: no retries on definitive 4xx, retries on 429/5xx, negative cache and scan budget (fail-closed)."""
import time, types
import pytest
import memebot


class R:
    def __init__(self, code, payload=None):
        self.status_code, self._p = code, payload or {}
    def raise_for_status(self):
        if self.status_code >= 400: raise RuntimeError(f"http {self.status_code}")
    def json(self): return self._p


def test_get_does_not_retry_on_400(monkeypatch):
    calls = []
    monkeypatch.setattr(memebot.requests, "get", lambda url, **k: calls.append(url) or R(400))
    monkeypatch.setattr(memebot.time, "sleep", lambda s: None)
    assert memebot.get("https://api.rugcheck.xyz/v1/tokens/x/report") is None
    assert len(calls) == 1


def test_get_retries_on_5xx_and_429_then_succeeds(monkeypatch):
    seq = [R(503), R(429), R(200, {"ok": 1})]
    monkeypatch.setattr(memebot.requests, "get", lambda url, **k: seq.pop(0))
    monkeypatch.setattr(memebot.time, "sleep", lambda s: None)
    assert memebot.get("https://example.test/x") == {"ok": 1}


def test_get_timeout_param_is_forwarded(monkeypatch):
    seen = {}
    def fake(url, **k): seen.update(k); return R(200, {})
    monkeypatch.setattr(memebot.requests, "get", fake)
    memebot.get("https://example.test/x", timeout=8, retries=1, foo="bar")
    assert seen["timeout"] == 8 and seen["params"] == {"foo": "bar"}


def _meme():
    s = types.SimpleNamespace(); s._rc, s._rc_fail = {}, {}
    return s


def test_prefetch_rug_caches_success_and_failure():
    s = _meme()
    s.rug = lambda m: {"mint_auth": None} if m == "good" else None
    fetched, late = memebot.Meme.prefetch_rug(s, ["good", "bad"], budget_s=5)
    assert fetched == 1 and late == 0
    assert "good" in s._rc and s._rc["good"][1] == {"mint_auth": None}
    assert "bad" in s._rc_fail and "bad" not in s._rc


def test_prefetch_rug_respects_budget_and_marks_pending_as_failed():
    s = _meme()
    def slow(m):
        time.sleep(1.5); return {"mint_auth": None}
    s.rug = slow
    t0 = time.time()
    fetched, late = memebot.Meme.prefetch_rug(s, [f"m{i}" for i in range(12)], budget_s=1, workers=4)
    assert time.time() - t0 < 4                 # returned at the budget, not after 12 x 1.5 s / 4
    assert late >= 1 and fetched + late + len([m for m in s._rc_fail]) >= 12
    assert all(m in s._rc or m in s._rc_fail for m in [f"m{i}" for i in range(12)])


def test_prefetch_rug_empty():
    s = _meme(); s.rug = lambda m: None
    assert memebot.Meme.prefetch_rug(s, [], budget_s=1) == (0, 0)
