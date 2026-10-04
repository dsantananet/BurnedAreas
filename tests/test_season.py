import importlib.util
from datetime import date
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('season',Path(__file__).resolve().parents[1]/'seasonal/update_season.py')
season = importlib.util.module_from_spec(spec)
spec.loader.exec_module(season)

class SeasonTests(unittest.TestCase):
    def test_current_year_stops_before_today(self):
        self.assertEqual(season.season_dates(2026,date(2026,10,4)),(date(2026,5,1),date(2026,10,4)))

    def test_completed_year_stops_before_november(self):
        self.assertEqual(season.season_dates(2025,date(2026,10,4)),(date(2025,5,1),date(2025,11,1)))

    def test_future_season_rejected(self):
        with self.assertRaises(ValueError):
            season.season_dates(2027,date(2026,10,4))
