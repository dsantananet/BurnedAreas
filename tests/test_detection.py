"""Regression checks for missing imagery and non-overlapping date windows."""
import json
import os
from pathlib import Path
import runpy
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'detect_burnt_areas.py'


class FakeEE:
    def __init__(self, counts):
        self.counts = iter(counts)
        self.dates = []

    def filterDate(self, start, end):
        self.dates.append((start, end))
        return self

    def size(self):
        count = next(self.counts)
        return types.SimpleNamespace(getInfo=lambda: count)

    def getInfo(self):
        return {'type': 'FeatureCollection', 'features': []}

    def __getattr__(self, name):
        return lambda *args, **kwargs: self


class DetectionTests(unittest.TestCase):
    def run_case(self, counts):
        fake = FakeEE(counts)
        module = types.SimpleNamespace(
            ServiceAccountCredentials=lambda *a, **kw: None,
            Initialize=lambda *a: None,
            Geometry=types.SimpleNamespace(Rectangle=lambda *a: None),
            ImageCollection=lambda *a: fake,
        )
        with tempfile.TemporaryDirectory() as directory:
            previous = os.getcwd()
            try:
                os.chdir(directory)
                with patch.dict(sys.modules, {'ee': module}), patch.dict(
                    os.environ, {'GEE_SERVICE_ACCOUNT_KEY': '{"client_email":"test@example.invalid"}'}
                ):
                    runpy.run_path(str(SCRIPT))
                report = json.loads(Path('outputs/run_status.json').read_text())
                geojson = json.loads((Path('outputs') / report['geojson']).read_text())
                self.assertEqual(geojson['type'], 'FeatureCollection')
                return report, fake.dates
            finally:
                os.chdir(previous)

    def test_no_post_images_is_explicit(self):
        report, _ = self.run_case([0, 0])
        self.assertEqual(report['status'], 'no_post_images')
        self.assertEqual(report['post_image_count'], 0)

    def test_missing_pre_images_does_not_select_absent_bands(self):
        report, _ = self.run_case([1, 0])
        self.assertEqual(report['status'], 'no_pre_images')

    def test_fallback_pre_window_ends_before_post_window(self):
        report, dates = self.run_case([0, 2, 3])
        self.assertEqual(report['status'], 'processed')
        self.assertEqual(dates[2][1], dates[1][0])
        self.assertEqual(report['pre_end_exclusive'], report['post_start'])


if __name__ == '__main__':
    unittest.main()
