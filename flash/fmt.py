# -*- coding: utf-8 -*-
"""Canonical display formatting — the second half of BR-5.

BR-5 says every metric is computed in exactly one place. That stops the four
surfaces disagreeing about the *value*. It does not, on its own, stop them
disagreeing about the *rendering* — one surface rounding $412,449 to "$412K"
and another to "$412.4K" is the same defect wearing a different hat, and it is
the one a CFO notices first.

So the display strings are computed once too. `compute.py` attaches them to the
computed object under `display`; the renderers print those strings and never
re-format a number themselves. `tests/test_render.py` asserts the strings
appear verbatim in all four surfaces.

Stdlib only. No locale dependence (locale would make output machine-specific
and break NFR-2's byte-identical requirement).
"""

from __future__ import annotations

import datetime as dt
from typing import Optional

DASH = "—"          # em dash
MINUS = "−"         # true minus sign, so figures align in tabular-nums
NA = "n/a"


def money_compact(v: Optional[float]) -> str:
    """Headline money: $1.24M / $412.4K / $938. Sign kept for negatives."""
    if v is None:
        return NA
    sign = MINUS if v < 0 else ""
    a = abs(float(v))
    if a >= 1_000_000:
        return "%s$%.2fM" % (sign, a / 1_000_000.0)
    if a >= 1_000:
        return "%s$%.1fK" % (sign, a / 1_000.0)
    return "%s$%d" % (sign, int(round(a)))


def money_exact(v: Optional[float]) -> str:
    """Ledger money: $412,449.13 — the reconciliation figures use this."""
    if v is None:
        return NA
    sign = MINUS if v < 0 else ""
    return "%s$%s" % (sign, "{:,.2f}".format(abs(float(v))))


def money_signed(v: Optional[float]) -> str:
    """Deltas: +$12.4K / -$41.2K (compact, explicit + on gains)."""
    if v is None:
        return NA
    if v >= 0:
        return "+" + money_compact(v)
    return money_compact(v)


def pct(v: Optional[float], places: int = 1) -> str:
    """Signed percentage from a ratio-minus-one: +2.6% / -7.9%."""
    if v is None:
        return NA
    s = "%+.*f%%" % (places, v * 100.0)
    return s.replace("-", MINUS, 1) if v < 0 else s


def pct_plain(v: Optional[float], places: int = 1) -> str:
    """Unsigned percentage of a level (plan attainment, completeness): 99.4%."""
    if v is None:
        return NA
    return "%.*f%%" % (places, v * 100.0)


def count(v: Optional[float]) -> str:
    if v is None:
        return NA
    return "{:,}".format(int(round(v)))


def ratio(v: Optional[float], places: int = 2) -> str:
    if v is None:
        return NA
    return "%.*f" % (places, v)


def money_plain(v: Optional[float]) -> str:
    """AOV / AUR: $58.40."""
    if v is None:
        return NA
    sign = MINUS if v < 0 else ""
    return "%s$%.2f" % (sign, abs(float(v)))


# -- dates ----------------------------------------------------------------

def day_long(d) -> str:
    """Thursday, July 23, 2026 — platform-independent (no %-flags, no locale)."""
    d = _as_date(d)
    return "%s, %s %d, %d" % (WEEKDAYS[d.weekday()], MONTHS[d.month - 1],
                              d.day, d.year)


def day_short(d) -> str:
    """Thu Jul 23."""
    d = _as_date(d)
    return "%s %s %d" % (WEEKDAYS[d.weekday()][:3], MONTHS[d.month - 1][:3], d.day)


def day_short_year(d) -> str:
    """Thu Jul 24, 2025 — used whenever an LY date is shown."""
    d = _as_date(d)
    return "%s, %d" % (day_short(d), d.year)


def iso(d) -> str:
    return _as_date(d).isoformat()


WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday",
            "Friday", "Saturday", "Sunday")
MONTHS = ("January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December")


def _as_date(d):
    if isinstance(d, dt.date):
        return d
    return dt.date.fromisoformat(str(d))
