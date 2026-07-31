# -*- coding: utf-8 -*-
"""Calendar tests — the moat gets tested the hardest (PRD §4).

Run:  python3 -m unittest tests.test_calendar    (or python3 tests/test_calendar.py)
"""
import datetime as dt
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from flash.calendar import (
    NRFCalendar, PERIODS_PER_YEAR, dow_1sun, holiday_code,
    ly_holiday_aligned_date,
)

D = dt.date


class TestStructure(unittest.TestCase):
    def setUp(self):
        self.c = NRFCalendar()

    def test_years_tile_exactly(self):
        for fy in range(2020, 2036):
            pers = self.c.periods(fy)
            self.assertEqual(len(pers), 12, "FY%d period count" % fy)
            total = sum(p.weeks for p in pers)
            self.assertIn(total, (52, 53), "FY%d weeks" % fy)
            self.assertEqual(total, self.c.fy_week_count(fy))
            self.assertEqual(pers[0].start, self.c.fy_start_date(fy))
            self.assertEqual(pers[-1].end,
                             self.c.fy_start_date(fy + 1) - dt.timedelta(days=1))
            # 4-5-4 pattern (plus the 53rd week in P12 when present)
            base = [4, 5, 4] * 4
            for i, p in enumerate(pers):
                want = base[i] + (1 if (self.c.is_53_week_year(fy) and i == 11) else 0)
                self.assertEqual(p.weeks, want, "FY%d P%02d weeks" % (fy, i + 1))

    def test_53_week_years_present_and_absorbed_in_p12(self):
        fifties = [fy for fy in range(2020, 2036) if self.c.is_53_week_year(fy)]
        self.assertTrue(fifties, "a 53-week year must exist in 2020-2035")
        # documented actual result under Sunday-nearest-Feb-1
        self.assertIn(2023, fifties)
        self.assertIn(2028, fifties)
        for fy in fifties:
            self.assertEqual(self.c.period(fy, 12).weeks, 5)  # 4 + extra week

    def test_date_to_period_round_trip_across_boundary(self):
        for fy in (2023, 2024, 2028):   # include a 53-week year and its neighbour
            for per in self.c.periods(fy):
                for probe in (per.start, per.end, per.start + dt.timedelta(days=3)):
                    got = self.c.period_for_date(probe)
                    self.assertEqual((got.fiscal_year, got.period_no),
                                     (per.fiscal_year, per.period_no),
                                     "%s -> %s" % (probe, got.label))


class TestLabelDefects(unittest.TestCase):
    """The two Door-Engine bug classes the PRD says to test against (§4.5)."""

    def setUp(self):
        self.c = NRFCalendar()

    def test_parse_label_rejects_calendar_month(self):
        with self.assertRaises(ValueError):
            self.c.parse_label("2026-01")     # a calendar month, NOT a period
        with self.assertRaises(ValueError):
            self.c.parse_label("P01")
        with self.assertRaises(ValueError):
            self.c.parse_label("")

    def test_parse_label_round_trip(self):
        self.assertEqual(self.c.parse_label("FY26-P01"), (2026, 1))
        self.assertEqual(self.c.parse_label(self.c.label(2031, 12)), (2031, 12))

    def test_period_range_validation_blocks_negative_index(self):
        # period(fy, 0) must raise, not silently return periods[-1] (P12 of the
        # SAME year) — a future period inside a history window.
        with self.assertRaises(ValueError):
            self.c.period(2026, 0)
        with self.assertRaises(ValueError):
            self.c.period(2026, PERIODS_PER_YEAR + 1)


class TestDayAlignedLY(unittest.TestCase):
    def setUp(self):
        self.c = NRFCalendar()

    def test_same_day_of_week(self):
        for iso in ("2026-07-23", "2026-02-01", "2025-11-28", "2026-05-10"):
            d = D.fromisoformat(iso)
            ly, _ = self.c.ly_aligned_date(d)
            self.assertEqual(dow_1sun(ly), dow_1sun(d), "DOW mismatch for %s" % iso)

    def test_normal_year_is_364_day_offset(self):
        d = D(2026, 7, 23)                 # FY2026 vs FY2025, both 52-week
        ly, restated = self.c.ly_aligned_date(d)
        self.assertEqual((d - ly).days, 364)
        self.assertFalse(restated)

    def test_holiday_shift_raw_differs_from_adjusted(self):
        j4 = D(2026, 7, 4)                  # Saturday in 2026
        self.assertEqual(holiday_code(j4), "JULY_4")
        raw, _ = self.c.ly_aligned_date(j4)         # week/day aligned
        adjusted = ly_holiday_aligned_date(j4)      # same holiday last year
        self.assertEqual(adjusted, D(2025, 7, 4))   # Friday in 2025
        self.assertNotEqual(raw, adjusted)          # the shift is visible
        self.assertIsNone(ly_holiday_aligned_date(D(2026, 7, 23)))  # non-holiday

    def test_53_week_restatement_flag(self):
        # FY2024 (52w) comps against FY2023 (53w): boundary -> restated (BR-8).
        _, restated = self.c.ly_aligned_date(D(2024, 6, 1))
        self.assertTrue(restated)
        # Week 53 of a 53-week year folds onto prior-year week 52, same DOW.
        wk53_start = self.c.fy_start_date(2028) + dt.timedelta(days=52 * 7)
        self.assertEqual(self.c.week_of(wk53_start), 53)
        ly, restated = self.c.ly_aligned_date(wk53_start)
        self.assertTrue(restated)
        self.assertEqual(dow_1sun(ly), dow_1sun(wk53_start))
        self.assertEqual(self.c.week_of(ly), 52)     # folded, not week 53


if __name__ == "__main__":
    unittest.main(verbosity=2)
