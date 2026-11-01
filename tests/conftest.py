"""Tests must not depend on what runs on the host: process lookups return nothing (the bot may be running on the same machine).
The tests of _pgrep itself keep the real function."""
import pytest
import dash_data

@pytest.fixture(autouse=True)
def _no_host_processes(request, monkeypatch):
    if "pgrep" in request.node.name: return
    monkeypatch.setattr(dash_data, "_pgrep", lambda *a, **k: [])
