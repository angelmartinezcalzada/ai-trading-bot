"""Coinversa Pulse client: Hyperliquid positioning / liquidation context for the CFO review and the dashboard.

Design rules (see DECISIONS.md 2026-10-31 "MVP Hyperliquid"):
  * Coinversa is a RISK/CONTEXT layer, not an alpha signal: a 30-day study (research/coinversa_study.py) found no
    consistent predictive power of cohort bias on 1h-24h returns (pooled |corr| < 0.11, sign inconsistent across coins).
  * Everything here is fail-safe: a failed call returns None / empty flags and never blocks trading logic.
  * The REST paths below mirror the routes the Coinversa MCP server reports as its sources; confirm them against
    https://coinversa.ai/developers before relying on them (set COINVERSA_BASE_URL / COINVERSA_ENDPOINTS_JSON to override).
"""
from __future__ import annotations
import json, os, time, logging
from typing import Any, Optional
log = logging.getLogger("hl.coinversa")

DEFAULT_BASE = "https://api.coinversa.ai"
DEFAULT_ENDPOINTS = {
    "cohort_bias": "/live/cohort-bias",               # ?coin=BTC
    "risk_snapshot": "/live/risk/coin",               # ?coin=BTC
    "liq_heatmap": "/live/risk/liquidations/heatmap", # ?coin=BTC&range=30&buckets=50
    "risk_overview": "/live/risk/overview",
}
TIER_LABEL = {"money_printer": "apex", "smart_money": "sharps", "grinder": "grinders", "humble_earner": "scrapers",
              "exit_liquidity": "crowd", "semi_rekt": "bleeders", "full_rekt": "trapped", "giga_rekt": "blown_out"}


class CoinversaError(RuntimeError):
    pass


class CoinversaClient:
    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None, timeout: float = 15.0,
                 session=None, endpoints: Optional[dict] = None):
        self.api_key = api_key if api_key is not None else os.environ.get("COINVERSA_API_KEY", "")
        self.base = (base_url or os.environ.get("COINVERSA_BASE_URL") or DEFAULT_BASE).rstrip("/")
        self.timeout = timeout
        self.endpoints = dict(DEFAULT_ENDPOINTS)
        env_ep = os.environ.get("COINVERSA_ENDPOINTS_JSON")
        if env_ep:
            try: self.endpoints.update(json.loads(env_ep))
            except Exception as e: log.warning("COINVERSA_ENDPOINTS_JSON ignored: %s", e)
        if endpoints: self.endpoints.update(endpoints)
        self._session = session
        self._cache: dict[tuple, tuple[float, Any]] = {}

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def _get(self, name: str, cache_s: int = 60, **params) -> Optional[dict]:
        """GET one endpoint; None on any failure (fail-safe). Small in-memory cache to respect rate limits."""
        if not self.enabled: return None
        key = (name, tuple(sorted(params.items())))
        hit = self._cache.get(key)
        if hit and time.time() - hit[0] < cache_s: return hit[1]
        try:
            url = self.base + self.endpoints[name]
            if self._session is None:
                import requests
                self._session = requests.Session()
            r = self._session.get(url, params=params or None, timeout=self.timeout, allow_redirects=False,   # never follow a redirect carrying the key to another host
                                  headers={"Authorization": f"Bearer {self.api_key}", "X-API-Key": self.api_key,
                                           "Accept": "application/json"})
            if r.status_code == 429:
                log.warning("coinversa 429 on %s", name); return None
            r.raise_for_status()
            data = r.json()
            self._cache[key] = (time.time(), data)
            return data
        except Exception as e:
            log.warning("coinversa %s failed: %s", name, e)
            return None

    def cohort_bias(self, coin: str) -> Optional[dict]:
        return self._get("cohort_bias", coin=coin)

    def risk_snapshot(self, coin: str) -> Optional[dict]:
        return self._get("risk_snapshot", coin=coin)

    def liquidation_heatmap(self, coin: str, rng: int = 30, buckets: int = 50) -> Optional[dict]:
        return self._get("liq_heatmap", cache_s=120, coin=coin, range=rng, buckets=buckets)

    def risk_overview(self) -> Optional[dict]:
        return self._get("risk_overview", cache_s=120)


# ---------------------------------------------------------------- pure helpers (unit-tested, no network) -----------
def tier_bias(bias: Optional[dict]) -> dict[str, float]:
    """{'apex': netBiasByNotional, 'sharps': ..., 'crowd': ...} from a cohort-bias payload; missing -> {}."""
    out: dict[str, float] = {}
    for t in (bias or {}).get("tiers") or []:
        if not isinstance(t, dict): continue
        label = TIER_LABEL.get(t.get("tier"), (t.get("label") or t.get("tier") or "").lower().replace("the ", ""))
        try: out[label] = float(t.get("netBiasByNotional"))
        except (TypeError, ValueError): continue
    return out


def _num(x) -> Optional[float]:
    try: return float(x) if x is not None and not isinstance(x, (dict, list)) else None
    except (TypeError, ValueError): return None


def snapshot_numbers(snapshot: Optional[dict], side: str = "long") -> dict:
    """Open interest, notional near liquidation and average leverage from a coin risk snapshot, whatever the payload shape:
    the live API nests them as market.totalOi / market.avgLongLeverage / market.avgShortLeverage with nearLiquidationNotional at
    the top level; older shapes used totalOI / avgLeverage. Missing values stay None (never 0: a 0 would read as 'no risk')."""
    s = snapshot or {}; mk = s.get("market") if isinstance(s.get("market"), dict) else {}
    oi = next((v for v in (_num(s.get("totalOI")), _num(mk.get("totalOi")), _num(mk.get("openInterest")), _num(s.get("openInterest"))) if v), None)
    near = s.get("nearLiquidationNotional")
    if isinstance(near, dict): near = near.get(side) or near.get(f"{side}Notional")
    lev_key = "avgLongLeverage" if side == "long" else "avgShortLeverage"
    lev = next((v for v in (_num(mk.get(lev_key)), _num(s.get(lev_key)), _num(mk.get("avgLeverage")), _num(s.get("avgLeverage"))) if v), None)
    return {"oi": oi, "near_liq": _num(near), "avg_leverage": lev}


def risk_flags(side: str, bias: Optional[dict] = None, snapshot: Optional[dict] = None,
               crowd_thr: float = 0.5, apex_thr: float = 0.3, liq_ratio_thr: float = 0.10,
               leverage_thr: float = 12.0) -> list[str]:
    """Context flags for an open or planned position on `side` ('long'|'short'). Flags only inform the review and the
    dashboard; they never relax a veto and never increase size.
      crowd_with_us   : The Crowd (exit_liquidity tier) is strongly on our side (> crowd_thr) -> crowded trade.
      apex_against    : Apex (money_printer tier) notional bias is against us by more than apex_thr.
      liq_cluster     : notional near liquidation on OUR side is > liq_ratio_thr of the coin's OI (cascade risk).
      high_leverage   : average leverage on the coin above leverage_thr.
    """
    sgn = 1.0 if side == "long" else -1.0
    flags: list[str] = []
    tb = tier_bias(bias)
    if "crowd" in tb and tb["crowd"] * sgn > crowd_thr: flags.append("crowd_with_us")
    if "apex" in tb and tb["apex"] * sgn < -apex_thr: flags.append("apex_against")
    n = snapshot_numbers(snapshot, side)
    if n["oi"] and n["near_liq"] is not None and n["near_liq"] / n["oi"] > liq_ratio_thr: flags.append("liq_cluster")
    if n["avg_leverage"] is not None and n["avg_leverage"] > leverage_thr: flags.append("high_leverage")
    return flags


def size_multiplier(flags: list[str]) -> float:
    """Advisory size multiplier in [0.5, 1]: only ever reduces. 0.75 for a crowded trade or Apex against it, 0.5625 for both,
    0.85 for a liquidation cluster on our side; the product never goes below the 0.5 floor (all three flags -> 0.5)."""
    m = 1.0
    if "crowd_with_us" in flags: m *= 0.75
    if "apex_against" in flags: m *= 0.75
    if "liq_cluster" in flags: m *= 0.85
    return max(0.5, round(m, 3))


def context_row(coin: str, bias: Optional[dict], snapshot: Optional[dict], ts: Optional[float] = None) -> dict:
    """Flat row for data/hl_context.csv."""
    tb = tier_bias(bias); s = snapshot or {}; nl, ns = snapshot_numbers(s, "long"), snapshot_numbers(s, "short")
    lev = max(x for x in (nl["avg_leverage"], ns["avg_leverage"]) if x is not None) if (nl["avg_leverage"] or ns["avg_leverage"]) else None
    return {"time": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() if ts is None else ts)), "coin": coin,
            "apex": tb.get("apex"), "sharps": tb.get("sharps"), "crowd": tb.get("crowd"),
            "oi": nl["oi"], "near_liq": nl["near_liq"], "avg_leverage": lev, "flags_long": "|".join(risk_flags("long", bias, s)),
            "flags_short": "|".join(risk_flags("short", bias, s))}
