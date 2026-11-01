#!/usr/bin/env python3
"""Preview of the v2 panel with the SYNTHETIC fixture (never real data; symbols FIX*, mints 'Fixture…').

    python3 tools/preview_dashboard.py <dir> [--port 8790] [--now EPOCH] [--fixture-only] [--empty]

Writes the fixture into <dir> (tests/dash_fixture.make_fixture; with --empty only config.json via make_empty plus the
password file, to preview the "sin datos" path), copies dashboard.py, dash_data.py, live_view.py and
dashboard_v2.html next to it (a placeholder page when dashboard_v2.html does not exist yet, so /api/overview can be
exercised anyway) and serves Flask on 127.0.0.1:<port> with cwd=<dir>. Login password: "fixture".
Used for the Playwright screenshots (1280 px and 390 px). Nothing in the real bot folder is touched.
"""
import os, sys, time, shutil, argparse

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
PLACEHOLDER = """<!doctype html><html lang=es><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Panel v2 (pendiente)</title><body style="font-family:system-ui;background:#0d0d0d;color:#f0efec;padding:16px">
<h1>dashboard_v2.html todavía no existe en el repositorio</h1>
<p>La API ya responde: <a href="/api/overview" style="color:#3987e5">/api/overview</a>. CSRF inyectado: <code>{{csrf}}</code></p></html>"""


def prepare(d, now, empty=False):
    """Fixture (or the empty set) + code copies in `d`; returns the path of the served dashboard_v2.html."""
    d = os.path.abspath(d); os.makedirs(d, exist_ok=True)
    if ROOT not in sys.path: sys.path.insert(0, ROOT)
    from tests.dash_fixture import make_fixture, make_empty
    if empty:   # config.json only; dashboard.py still needs a password file at import time (same "fixture" password)
        make_empty(d); open(os.path.join(d, "dashboard_password.txt"), "w", encoding="utf-8").write("fixture\n")
    else: make_fixture(d, now)
    for f in ("dashboard.py", "dash_data.py", "live_view.py"): shutil.copy(os.path.join(ROOT, f), os.path.join(d, f))
    src, dst = os.path.join(ROOT, "dashboard_v2.html"), os.path.join(d, "dashboard_v2.html")
    if os.path.exists(src): shutil.copy(src, dst)
    else:
        open(dst, "w", encoding="utf-8").write(PLACEHOLDER)
        print("aviso: dashboard_v2.html no existe en el repo; se sirve un marcador de posición", file=sys.stderr)
    return dst


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dir", help="carpeta de trabajo (se crea; solo contiene el fixture sintético)")
    ap.add_argument("--port", type=int, default=8790); ap.add_argument("--now", type=float, default=None, help="epoch del fixture (por defecto, ahora)")
    ap.add_argument("--fixture-only", action="store_true", help="solo escribe el fixture y los ficheros; no arranca Flask")
    ap.add_argument("--empty", action="store_true", help="solo config.json (make_empty): vista previa del camino 'sin datos'")
    a = ap.parse_args(argv)
    now = a.now if a.now is not None else time.time(); d = os.path.abspath(a.dir)
    prepare(d, now, empty=a.empty)
    print(f"{'fixture vacío' if a.empty else 'fixture'} en {d} (now={now:.0f}); contraseña: fixture", flush=True)
    if a.fixture_only: return 0
    os.chdir(d); sys.path.insert(0, d)
    for m in ("dashboard", "live_view", "dash_data"): sys.modules.pop(m, None)
    import dashboard   # D = <dir>: reads <dir>/dashboard_password.txt, writes <dir>/.flask_secret
    print(f"http://127.0.0.1:{a.port}/  (login: fixture)", flush=True)
    dashboard.app.run(host="127.0.0.1", port=a.port, threaded=True)
    return 0


if __name__ == "__main__": sys.exit(main())
