import importlib.util
from pathlib import Path
import unittest
from datetime import date

spec = importlib.util.spec_from_file_location('forest', Path(__file__).parents[1]/'forest/pipeline.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class ForestTests(unittest.TestCase):
    def test_threshold_boundaries_have_no_gaps(self):
        self.assertEqual([m.severity_class(v) for v in [-1, -.1, .099, .1, .27, .44, .66, 1.5]], [0, 1, 1, 2, 3, 4, 5, 5])
        self.assertIsNone(m.severity_class(None))
        self.assertIsNone(m.severity_class(float('nan')))

    def test_recent_fire_does_not_use_future_observations(self):
        w = m.windows('2026-10-25', date(2026, 10, 25))
        self.assertGreater(w['post_start'], w['post_end_exclusive'])
        self.assertEqual(w['pre_end_exclusive'], '2026-10-20')

    def test_old_fire_has_fixed_post_window(self):
        w = m.windows('2026-08-01', date(2026, 10, 25))
        self.assertEqual(w['post_end_exclusive'], '2026-09-16')

    def test_event_id_changes_with_geometry_or_burn_date(self):
        f = {'geometry': {'type': 'Point', 'coordinates': [1, 2]}, 'properties': {'burn_date': '2026-01-01'}}
        first = m.stable_id(f)
        self.assertEqual(first, m.stable_id(f))
        f['properties']['burn_date'] = '2026-01-02'
        self.assertNotEqual(first, m.stable_id(f))
