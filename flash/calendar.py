# -*- coding: utf-8 -*-
"""NRF 4-5-4 retail fiscal calendar — the moat.

Adapted from the discipline of `Portfolio Analysis/tools/fiscal_calendar.py`
(a 4-4-5 July-start calendar), NOT transplanted: this is 4-5-4, Sunday-week,
fiscal year starting the Sunday nearest Feb 1 (PRD D1 / Strategy §7 D1).

The two defect classes the Door-Engine calendar's bug list calls out are
tested against here (see tests/test_calendar.py):

  * `parse_label` must REJECT calendar months like "2026-01" — accepting them
    silently maps January to fiscal period 1, a whole period out.
  * `period(fy, period_no)` must RANGE-VALIDATE — a caller computing
    `period_no - 1` and reaching 0 would otherwise get `periods[-1]`, Python's
    negative index handing back the LAST period of the same year (a future
    period inside a history window) with nothing downstream noticing.

Standard library only. No config file — the NRF parameters are fixed by the
owner decision (D1) and live here as named constants so there is one home for
the calendar shape.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Dict, List, Optional, Tuple

D = dt.date

# --- NRF 4-5-4 parameters (owner decision D1) -----------------------------
FY_START_MONTH = 2            # anchor the fiscal year to Feb 1 ...
FY_START_DAY = 1
WEEK_START = 6                # ... snapped to the NEAREST Sunday.
                             #  Python weekday(): Mon=0 .. Sun=6.
PERIODS_PER_YEAR = 12
QUARTER_PATTERN = (4, 5, 4)   # weeks per period within each quarter (4-5-4)
WEEK_53_PERIOD = 12           # the 53rd week lands in the last period (NRF)

_LABEL_RE = re.compile(r"^FY(\d{2,4})-P(\d{1,2})$", re.IGNORECASE)


def dow_1sun(day: dt.date) -> int:
    """Day of week with 1=Sunday .. 7=Saturday (PRD calendar convention)."""
    return ((day.weekday() + 1) % 7) + 1


class Period(object):
    """One fiscal period (a 'month' in a 4-5-4 calendar)."""

    __slots__ = ("fiscal_year", "period_no", "quarter", "weeks", "start", "end")

    def __init__(self, fiscal_year, period_no, quarter, weeks, start, end):
        self.fiscal_year = fiscal_year
        self.period_no = period_no
        self.quarter = quarter
        self.weeks = weeks
        self.start = start
        self.end = end

    @property
    def label(self) -> str:
        return "FY%02d-P%02d" % (self.fiscal_year % 100, self.period_no)

    def __repr__(self) -> str:
        return "<Period %s %s..%s %dw>" % (
            self.label, self.start.isoformat(), self.end.isoformat(), self.weeks)


class NRFCalendar(object):
    """NRF 4-5-4 calendar generator.

    Fiscal year `fy` starts on the Sunday nearest to Feb 1 of calendar year
    `fy` and runs whole weeks until the day before FY `fy+1` starts — 52 weeks
    (364 days) or 53 weeks (371 days). The extra week of a 53-week year is
    added to period 12.
    """

    def __init__(self):
        self._period_cache = {}   # type: Dict[int, List[Period]]
        # sanity on the shape itself (fails loudly if constants are edited wrong)
        if sum(QUARTER_PATTERN) * 4 != 52:
            raise ValueError("QUARTER_PATTERN must total 13 weeks per quarter")
        if len(QUARTER_PATTERN) * 4 != PERIODS_PER_YEAR:
            raise ValueError("QUARTER_PATTERN must tile PERIODS_PER_YEAR")

    # -- fiscal year boundaries -------------------------------------------

    @staticmethod
    def _snap_to_nearest_sunday(anchor: dt.date) -> dt.date:
        forward = (WEEK_START - anchor.weekday()) % 7
        backward = (anchor.weekday() - WEEK_START) % 7
        # nearest; ties (both == 0 impossible, both == ... ) resolve forward
        if forward <= backward:
            return anchor + dt.timedelta(days=forward)
        return anchor - dt.timedelta(days=backward)

    def fy_start_date(self, fiscal_year: int) -> dt.date:
        anchor = dt.date(fiscal_year, FY_START_MONTH, FY_START_DAY)
        return self._snap_to_nearest_sunday(anchor)

    def fy_week_count(self, fiscal_year: int) -> int:
        days = (self.fy_start_date(fiscal_year + 1)
                - self.fy_start_date(fiscal_year)).days
        if days not in (364, 371):
            raise AssertionError(
                "FY%d spans %d days; an NRF year must be 364 or 371"
                % (fiscal_year, days))
        return days // 7

    def is_53_week_year(self, fiscal_year: int) -> bool:
        return self.fy_week_count(fiscal_year) == 53

    # -- periods -----------------------------------------------------------

    def period_week_counts(self, fiscal_year: int) -> List[int]:
        weeks = list(QUARTER_PATTERN * 4)
        if self.is_53_week_year(fiscal_year):
            weeks[WEEK_53_PERIOD - 1] += 1
        return weeks

    def periods(self, fiscal_year: int) -> List[Period]:
        if fiscal_year in self._period_cache:
            return self._period_cache[fiscal_year]
        counts = self.period_week_counts(fiscal_year)
        cursor = self.fy_start_date(fiscal_year)
        out = []
        for idx, weeks in enumerate(counts):
            end = cursor + dt.timedelta(days=weeks * 7 - 1)
            out.append(Period(
                fiscal_year=fiscal_year,
                period_no=idx + 1,
                quarter=idx // len(QUARTER_PATTERN) + 1,
                weeks=weeks,
                start=cursor,
                end=end,
            ))
            cursor = end + dt.timedelta(days=1)
        if cursor != self.fy_start_date(fiscal_year + 1):
            raise AssertionError("FY%d periods do not tile the year exactly"
                                 % fiscal_year)
        self._period_cache[fiscal_year] = out
        return out

    def period(self, fiscal_year: int, period_no: int) -> Period:
        """One period. `period_no` is 1-based and validated (load-bearing)."""
        if not 1 <= period_no <= PERIODS_PER_YEAR:
            raise ValueError(
                "fiscal period %d is out of range for FY%d: periods are 1..%d. "
                "To step across a year boundary use prior_period()/sequence()."
                % (period_no, fiscal_year, PERIODS_PER_YEAR))
        return self.periods(fiscal_year)[period_no - 1]

    def prior_period(self, fiscal_year: int, period_no: int) -> Period:
        if period_no > 1:
            return self.period(fiscal_year, period_no - 1)
        return self.period(fiscal_year - 1, PERIODS_PER_YEAR)

    def period_for_date(self, day: dt.date) -> Period:
        for fy in (day.year - 1, day.year, day.year + 1):
            if self.fy_start_date(fy) <= day < self.fy_start_date(fy + 1):
                for per in self.periods(fy):
                    if per.start <= day <= per.end:
                        return per
        raise ValueError("no fiscal period contains %s" % day.isoformat())

    # -- week / day resolution --------------------------------------------

    def fiscal_year_of(self, day: dt.date) -> int:
        for fy in (day.year - 1, day.year, day.year + 1):
            if self.fy_start_date(fy) <= day < self.fy_start_date(fy + 1):
                return fy
        raise ValueError("no fiscal year contains %s" % day.isoformat())

    def week_of(self, day: dt.date) -> int:
        """Fiscal week number 1..52/53 (weeks run Sunday..Saturday)."""
        fy = self.fiscal_year_of(day)
        return (day - self.fy_start_date(fy)).days // 7 + 1

    def coordinates(self, day: dt.date) -> Tuple[int, int, int, int]:
        """(fiscal_year, period_no, week_no, dow_1sun) for a date."""
        per = self.period_for_date(day)
        return (per.fiscal_year, per.period_no, self.week_of(day), dow_1sun(day))

    # -- day-aligned last year (BR-1 / BR-8) ------------------------------

    def ly_aligned_date(self, day: dt.date) -> Tuple[dt.date, bool]:
        """Same fiscal week + same day-of-week, prior fiscal year (BR-1).

        Returns (aligned_date, restated) where `restated` marks a 53-week
        boundary that required the NRF one-week shift (BR-8).

        Normal case: prior FY has the same week number, so the counterpart is
        FY-1 start + (week-1)*7 + (dow-1). The 53-week edges:

          * current year has week 53 but prior year is 52-week -> fold onto
            prior-year week 52, same DOW (restated).
          * current year is 52-week but prior year was 53-week -> the prior
            year carried an extra week; weeks still map 1:1 by number, but we
            flag the comparison as restated so the flash discloses it.
        """
        fy, _p, week, dow = self.coordinates(day)
        prior_fy = fy - 1
        prior_weeks = self.fy_week_count(prior_fy)
        restated = False
        target_week = week
        if week > prior_weeks:            # week 53 with a 52-week prior year
            target_week = prior_weeks
            restated = True
        elif self.is_53_week_year(prior_fy) != self.is_53_week_year(fy):
            # week counts differ across the boundary -> disclose restatement
            restated = True
        aligned = (self.fy_start_date(prior_fy)
                   + dt.timedelta(days=(target_week - 1) * 7 + (dow - 1)))
        return aligned, restated

    # -- labels ------------------------------------------------------------

    def label(self, fiscal_year: int, period_no: int) -> str:
        return self.period(fiscal_year, period_no).label

    def parse_label(self, label: str) -> Tuple[int, int]:
        """'FY26-P01' -> (2026, 1). The FY/P prefixes are REQUIRED.

        Without that check a calendar month such as '2026-01' parses cleanly
        as FY2026-P01 — silently mapping January to fiscal period 1, a whole
        period out in a Feb-start calendar. Rejected loudly (see module docs).
        """
        m = _LABEL_RE.match((label or "").strip())
        if not m:
            raise ValueError(
                "period label %r is not FYyy-Pnn (e.g. FY26-P01). Calendar "
                "months such as '2026-01' are not fiscal periods." % (label,))
        fy = int(m.group(1))
        period_no = int(m.group(2))
        if fy < 100:
            fy += 2000
        if not 1 <= period_no <= PERIODS_PER_YEAR:
            raise ValueError("period %d out of range in label %r"
                             % (period_no, label))
        return fy, period_no


# --- holiday map (PRD §4.3) ----------------------------------------------
# Explicit, per calendar year. Codes are stable strings used for the LY
# holiday-override join. Floating holidays are computed; fixed-date holidays
# carry a floating weekday but a fixed month/day.

def _easter(year: int) -> dt.date:
    """Anonymous Gregorian algorithm (Meeus/Jones/Butcher)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    ell = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ell) // 451
    month = (h + ell - 7 * m + 114) // 31
    day = ((h + ell - 7 * m + 114) % 31) + 1
    return dt.date(year, month, day)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> dt.date:
    """n-th `weekday` (Mon=0..Sun=6) of month; n<0 counts from the end."""
    if n > 0:
        first = dt.date(year, month, 1)
        offset = (weekday - first.weekday()) % 7
        return first + dt.timedelta(days=offset + 7 * (n - 1))
    # last: start at month end
    if month == 12:
        nxt = dt.date(year + 1, 1, 1)
    else:
        nxt = dt.date(year, month + 1, 1)
    last = nxt - dt.timedelta(days=1)
    offset = (last.weekday() - weekday) % 7
    return last - dt.timedelta(days=offset)


def holidays_for_calendar_year(year: int) -> Dict[dt.date, str]:
    """Map of date -> holiday_code for one calendar year."""
    easter = _easter(year)
    thanksgiving = _nth_weekday(year, 11, 3, 4)  # 4th Thursday of November
    out = {
        dt.date(year, 1, 1): "NEW_YEARS_DAY",
        dt.date(year, 2, 14): "VALENTINES",
        easter: "EASTER",
        _nth_weekday(year, 5, 6, 2): "MOTHERS_DAY",       # 2nd Sunday of May
        _nth_weekday(year, 5, 0, -1): "MEMORIAL_DAY",      # last Monday of May
        dt.date(year, 7, 4): "JULY_4",
        _nth_weekday(year, 9, 0, 1): "LABOR_DAY",          # 1st Monday of Sept
        thanksgiving: "THANKSGIVING",
        thanksgiving + dt.timedelta(days=1): "BLACK_FRIDAY",
        thanksgiving + dt.timedelta(days=4): "CYBER_MONDAY",
        dt.date(year, 12, 24): "CHRISTMAS_EVE",
        dt.date(year, 12, 25): "CHRISTMAS_DAY",
        dt.date(year, 12, 31): "NEW_YEARS_EVE",
    }
    return out


def holiday_code(day: dt.date) -> Optional[str]:
    return holidays_for_calendar_year(day.year).get(day)


def holiday_date_in_year(code: str, year: int) -> Optional[dt.date]:
    """The date carrying `code` in a given calendar year (reverse lookup)."""
    for d, c in holidays_for_calendar_year(year).items():
        if c == code:
            return d
    return None


def ly_holiday_aligned_date(day: dt.date) -> Optional[dt.date]:
    """For a holiday date, the same holiday_code's date last year (PRD §4.3).

    Overrides week/day alignment. Returns None if `day` is not a holiday.
    """
    code = holiday_code(day)
    if code is None:
        return None
    return holiday_date_in_year(code, day.year - 1)
