import datetime as dt
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("terminplan", ROOT / "runtime/termine-pretix/terminplan.py")
plan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plan)


class TerminplanTest(unittest.TestCase):
    def test_standard_startet_am_naechsten_montag_auch_nach_jahreswechsel(self):
        for today, expected in (
            (dt.date(2026, 10, 15), dt.date(2026, 10, 19)),
            (dt.date(2026, 10, 19), dt.date(2026, 10, 26)),
            (dt.date(2026, 12, 31), dt.date(2027, 1, 4)),
        ):
            self.assertEqual(plan.startdatum(heute=today), expected)

    def test_startdatum_muss_zukuenftig_sein(self):
        today = dt.date(2026, 10, 15)
        self.assertEqual(plan.startdatum("2026-11-02", today), dt.date(2026, 11, 2))
        for value in ("2026-10-15", "2026-10-14", "2026-02-30", "ungültig"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                plan.startdatum(value, today)

    def test_ungueltige_kapazitaet_wird_abgewiesen(self):
        self.assertEqual(plan.zahl({}, "CAPACITY", 2, 1, 1000), 2)
        for value in ("0", "-1", "1001", "1.5"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                plan.zahl({"CAPACITY": value}, "CAPACITY", 2, 1, 1000)
