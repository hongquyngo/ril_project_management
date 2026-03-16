# utils/il_project/currency.py
"""
Currency utilities for IL Project Management.
Fully standalone — no imports from vendor_invoice or other app modules.

Rate resolution chain:
  1. In-memory cache  (TTL 1 hour)
  2. exchangeratesapi.io  (or any provider via EXCHANGE_RATE_API_KEY)
  3. exchange_rates table in DB  (fallback)
  4. Hardcoded fallback            (last resort, logged as warning)

Default target: VND — all IL project costs are converted to VND.

Public API:
    get_rate(from_ccy, to_ccy)        → RateResult
    get_rate_to_vnd(ccy)              → RateResult
    convert_to_vnd(amount, ccy)       → Optional[float]
    fmt_rate(rate)                    → str           (e.g. "25,300.00")
    rate_status(result)               → tuple[str, str]  (icon, message)
    get_currency_list()               → list[dict]     (id, code, name)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

import requests
from sqlalchemy import text

from ..db import get_db_engine

logger = logging.getLogger(__name__)


# ── Constants ─────────────────────────────────────────────────────────────────

TARGET_CURRENCY = "VND"

CACHE_TTL_SECONDS = 3600  # 1 hour

# Fallback rates (update periodically) — only used when both API and DB fail
_FALLBACK_RATES_TO_VND: dict[str, float] = {
    "USD": 25_300.0,
    "EUR": 27_500.0,
    "SGD": 19_000.0,
    "CNY":  3_500.0,
    "JPY":    175.0,
    "KRW":     19.0,
    "GBP": 32_000.0,
    "AUD": 16_500.0,
    "THB":    700.0,
    "MYR":  5_600.0,
}

# API provider
_API_URL = "http://api.exchangeratesapi.io/v1/convert"


# ── RateResult ─────────────────────────────────────────────────────────────────

@dataclass
class RateResult:
    """
    Exchange rate result.

    Attributes:
        from_currency:  Source currency
        to_currency:    Target currency
        rate:           Exchange rate (1 from = rate × to)
        source:         Rate source: 'same', 'cache', 'api', 'db', 'fallback'
        fetched_at:     Timestamp of fetch
        ok:             True if rate is reliable (api/db/same)
        warning:        Warning message when using fallback rate
    """
    from_currency: str
    to_currency:   str
    rate:          float
    source:        str                   # 'same' | 'cache' | 'api' | 'db' | 'fallback'
    fetched_at:    datetime = field(default_factory=datetime.now)
    ok:            bool = True
    warning:       Optional[str] = None

    @property
    def is_live(self) -> bool:
        """True if rate was fetched from API or DB (not a fallback)."""
        return self.source in ("same", "cache", "api", "db")

    def __str__(self) -> str:
        return f"1 {self.from_currency} = {fmt_rate(self.rate)} {self.to_currency} [{self.source}]"


# ── In-memory cache ────────────────────────────────────────────────────────────

@dataclass
class _CacheEntry:
    result: RateResult
    expires_at: datetime


_cache: dict[str, _CacheEntry] = {}


def _cache_get(key: str) -> Optional[RateResult]:
    entry = _cache.get(key)
    if entry and entry.expires_at > datetime.now():
        return entry.result
    _cache.pop(key, None)
    return None


def _cache_set(key: str, result: RateResult, ttl_seconds: int = CACHE_TTL_SECONDS) -> None:
    _cache[key] = _CacheEntry(result=result, expires_at=datetime.now() + timedelta(seconds=ttl_seconds))


def clear_cache() -> None:
    """Clear all cached exchange rates. Call to force a fresh fetch."""
    _cache.clear()
    logger.info("Exchange rate cache cleared.")


# ── Core rate-fetch logic ─────────────────────────────────────────────────────

def get_rate(from_currency: str, to_currency: str) -> RateResult:
    """
    Fetch exchange rate from from_currency to to_currency.
    Resolution chain: cache → API → DB → fallback.

    Example:
        result = get_rate("USD", "VND")
        print(result.rate)      # 25300.0
        print(result.source)    # 'api'
        print(result.ok)        # True
    """
    from_currency = from_currency.upper().strip()
    to_currency   = to_currency.upper().strip()

    # Same currency
    if from_currency == to_currency:
        return RateResult(from_currency, to_currency, 1.0, "same")

    cache_key = f"{from_currency}-{to_currency}"

    # 1. Cache
    cached = _cache_get(cache_key)
    if cached:
        logger.debug(f"Cache hit: {cache_key}")
        return cached

    # 2. API
    result = _fetch_from_api(from_currency, to_currency)
    if result:
        _cache_set(cache_key, result)
        _persist_to_db(result)
        return result

    # 3. DB
    result = _fetch_from_db(from_currency, to_currency)
    if result:
        _cache_set(cache_key, result)
        return result

    # 4. Fallback
    return _make_fallback(from_currency, to_currency)


def get_rate_to_vnd(currency: str) -> RateResult:
    """
    Convenience: fetch rate from currency → VND.
    This is the primary function used in IL project.

    Example:
        r = get_rate_to_vnd("USD")
        # r.rate = 25300.0
        # r.source = 'api'
    """
    return get_rate(currency, TARGET_CURRENCY)


def convert_to_vnd(amount: float, currency: str) -> Optional[float]:
    """
    Convert amount to VND.
    Returns None only if all 4 sources fail (extremely rare).

    Example:
        vnd = convert_to_vnd(1000, "USD")   # → 25_300_000.0
    """
    if currency == TARGET_CURRENCY:
        return float(amount)
    result = get_rate_to_vnd(currency)
    if result.rate <= 0:
        return None
    return round(float(amount) * result.rate, 0)


# ── API fetch ─────────────────────────────────────────────────────────────────

def _fetch_from_api(from_ccy: str, to_ccy: str) -> Optional[RateResult]:
    api_key = os.getenv("EXCHANGE_RATE_API_KEY")
    if not api_key:
        logger.debug("No EXCHANGE_RATE_API_KEY — skipping API fetch.")
        return None

    try:
        resp = requests.get(
            _API_URL,
            params={"access_key": api_key, "from": from_ccy, "to": to_ccy, "amount": 1},
            timeout=5,
        )
        resp.raise_for_status()
        data = resp.json()

        if data.get("success"):
            rate = data.get("result")
            if rate is not None and float(rate) > 0:
                logger.info(f"API rate {from_ccy}/{to_ccy}: {rate}")
                return RateResult(from_ccy, to_ccy, float(rate), "api")
            logger.warning(f"API returned invalid rate: {rate}")
        else:
            err_info = data.get("error", {}).get("info", "unknown")
            logger.warning(f"API error for {from_ccy}/{to_ccy}: {err_info}")

    except requests.Timeout:
        logger.warning(f"API timeout for {from_ccy}/{to_ccy}")
    except Exception as e:
        logger.error(f"API fetch error {from_ccy}/{to_ccy}: {e}")

    return None


# ── DB fetch ──────────────────────────────────────────────────────────────────

def _fetch_from_db(from_ccy: str, to_ccy: str) -> Optional[RateResult]:
    """Fetch exchange rate from the exchange_rates table in DB."""
    try:
        engine = get_db_engine()
        with engine.connect() as conn:
            # Direct rate
            row = conn.execute(text("""
                SELECT rate_value, rate_date
                FROM exchange_rates
                WHERE from_currency_code = :from_ccy
                  AND to_currency_code   = :to_ccy
                  AND delete_flag = 0
                ORDER BY rate_date DESC, created_date DESC
                LIMIT 1
            """), {"from_ccy": from_ccy, "to_ccy": to_ccy}).fetchone()

            if row and row[0] and float(row[0]) > 0:
                logger.info(f"DB rate {from_ccy}/{to_ccy}: {row[0]} (date: {row[1]})")
                return RateResult(from_ccy, to_ccy, float(row[0]), "db")

            # Inverse rate
            row_inv = conn.execute(text("""
                SELECT rate_value, rate_date
                FROM exchange_rates
                WHERE from_currency_code = :to_ccy
                  AND to_currency_code   = :from_ccy
                  AND delete_flag = 0
                ORDER BY rate_date DESC, created_date DESC
                LIMIT 1
            """), {"from_ccy": from_ccy, "to_ccy": to_ccy}).fetchone()

            if row_inv and row_inv[0] and float(row_inv[0]) > 0:
                rate = 1.0 / float(row_inv[0])
                logger.info(f"DB inverse rate {from_ccy}/{to_ccy}: {rate}")
                return RateResult(from_ccy, to_ccy, rate, "db")

    except Exception as e:
        logger.error(f"DB fetch error {from_ccy}/{to_ccy}: {e}")

    return None


# ── Persist to DB ──────────────────────────────────────────────────────────────

def _persist_to_db(result: RateResult) -> None:
    """
    Persist a freshly fetched API rate into exchange_rates as a DB cache.
    Uses INSERT ... ON DUPLICATE KEY UPDATE when a unique key exists (from, to, date).
    Silent fail — non-critical.
    """
    try:
        engine = get_db_engine()
        today  = result.fetched_at.date()
        with engine.connect() as conn:
            conn.execute(text("""
                INSERT INTO exchange_rates
                    (from_currency_code, to_currency_code, rate_value, rate_date, delete_flag,
                     created_by, created_date)
                VALUES
                    (:from_ccy, :to_ccy, :rate, :date, 0,
                     'SYSTEM_RATE_SYNC', NOW())
                ON DUPLICATE KEY UPDATE
                    rate_value    = :rate,
                    modified_date = NOW()
            """), {
                "from_ccy": result.from_currency,
                "to_ccy":   result.to_currency,
                "rate":     result.rate,
                "date":     today,
            })
            conn.commit()
            logger.debug(f"Persisted rate {result.from_currency}/{result.to_currency} to DB.")
    except Exception as e:
        logger.debug(f"Could not persist rate to DB (non-critical): {e}")


# ── Fallback ──────────────────────────────────────────────────────────────────

def _make_fallback(from_ccy: str, to_ccy: str) -> RateResult:
    """
    Last resort: use hardcoded fallback rates.
    Supports conversions via VND only (from → VND or cross via VND).
    """
    rate: Optional[float] = None

    # Direct fallback (X → VND)
    if to_ccy == TARGET_CURRENCY:
        rate = _FALLBACK_RATES_TO_VND.get(from_ccy)

    # Cross via VND (X → VND → Y)
    elif from_ccy in _FALLBACK_RATES_TO_VND and to_ccy in _FALLBACK_RATES_TO_VND:
        rate = _FALLBACK_RATES_TO_VND[from_ccy] / _FALLBACK_RATES_TO_VND[to_ccy]

    if rate is not None:
        warn = (
            f"Could not fetch {from_ccy}/{to_ccy} from API/DB. "
            f"Using reference rate ({rate:,.2f}). Please verify before use."
        )
        logger.warning(warn)
        return RateResult(from_ccy, to_ccy, rate, "fallback", ok=False, warning=warn)

    # Total failure
    warn = f"No rate available for {from_ccy}/{to_ccy} — returning 0."
    logger.error(warn)
    return RateResult(from_ccy, to_ccy, 0.0, "fallback", ok=False, warning=warn)


# ── Formatting ─────────────────────────────────────────────────────────────────

def fmt_rate(rate: Optional[float]) -> str:
    """
    Format exchange rate for display.
    Automatically selects appropriate decimal precision.

    Example:
        fmt_rate(25300.0)    → "25,300.00"
        fmt_rate(0.000039)   → "0.000039"
        fmt_rate(None)       → "N/A"
    """
    if rate is None:
        return "N/A"
    if rate >= 1_000:
        return f"{rate:,.2f}"
    if rate >= 10:
        return f"{rate:,.4f}"
    if rate >= 1:
        return f"{rate:,.6f}"
    # Tiny rates: find required decimal places
    decimals = 2
    tmp = rate
    while tmp < 0.1 and decimals < 10:
        tmp *= 10
        decimals += 1
    return f"{rate:.{decimals + 2}f}"


def rate_status(result: RateResult) -> tuple[str, str]:
    """
    Returns (icon, message) for displaying a status badge in the UI.
    No Streamlit import — caller uses icon+message with their own framework.

    Example:
        icon, msg = rate_status(result)
        st.success(f"{icon} {msg}")   # if ok
        st.warning(f"{icon} {msg}")   # if fallback
    """
    from_ccy = result.from_currency
    to_ccy   = result.to_currency

    if result.source == "same":
        return "ℹ️", f"{from_ccy} — no conversion needed"

    if not result.ok or result.source == "fallback":
        return "⚠️", (
            result.warning
            or f"Using reference rate: 1 {from_ccy} ≈ {fmt_rate(result.rate)} {to_ccy}"
        )

    source_label = {"api": "live API", "db": "DB cached", "cache": "memory"}.get(result.source, result.source)
    age_min = int((datetime.now() - result.fetched_at).total_seconds() / 60)
    age_str = f"{age_min}m ago" if age_min > 0 else "just now"
    return "✅", f"1 {from_ccy} = {fmt_rate(result.rate)} {to_ccy}  ({source_label}, {age_str})"


# ── Currency list ─────────────────────────────────────────────────────────────

def get_currency_list() -> list[dict]:
    """
    Return list of currencies from DB: [{id, code, name}, ...].
    Sorted: VND, USD, EUR, SGD first.
    Thread-safe; no @st.cache_data to avoid Streamlit dependency.
    Caller can cache with @st.cache_data(ttl=300) at page level.

    Example:
        currencies = get_currency_list()
        codes = [c['code'] for c in currencies]   # ['VND', 'USD', 'EUR', ...]
    """
    _priority = {"VND": 1, "USD": 2, "EUR": 3, "SGD": 4, "CNY": 5}
    try:
        engine = get_db_engine()
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT id, code, name
                FROM currencies
                WHERE delete_flag = 0 AND code IS NOT NULL
                ORDER BY code
            """)).fetchall()
        result = [{"id": r[0], "code": r[1], "name": r[2]} for r in rows]
        result.sort(key=lambda c: (_priority.get(c["code"], 99), c["code"]))
        return result
    except Exception as e:
        logger.error(f"get_currency_list failed: {e}")
        return []