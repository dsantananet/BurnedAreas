import importlib.util
from pathlib import Path
import unittest
from datetime import date
import tempfile
import json

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

    def test_batch_merge_preserves_newest_attempt_and_flags_missing_shards(self):
        merge_spec=importlib.util.spec_from_file_location('merge',Path(__file__).parents[1]/'forest/merge_batches.py')
        merge_module=importlib.util.module_from_spec(merge_spec);merge_spec.loader.exec_module(merge_module)
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);base=root/'in/forest-base';batch=root/'in/forest-shard-0'
            base.mkdir(parents=True);batch.mkdir()
            (base/'forest-status.json').write_text(json.dumps({'status':'processed','errors':[]}))
            (base/'events.json').write_text(json.dumps({'a':{'status':'queued'},'b':{'status':'processed','last_attempt':'2026-01-02'}}))
            (batch/'forest-status.json').write_text(json.dumps({'status':'processed','errors':[]}))
            (batch/'events.json').write_text(json.dumps({'a':{'status':'processed','last_attempt':'2026-01-03'},'b':{'status':'queued','last_attempt':'2026-01-01'}}))
            merge_module.merge(root/'in',root/'out')
            result=json.loads((root/'out/events.json').read_text())
            status=json.loads((root/'out/forest-status.json').read_text())
            self.assertEqual(result['a']['status'],'processed')
            self.assertEqual(result['b']['status'],'processed')
            self.assertEqual(status['completed'],2)
            self.assertEqual(status['status'],'partial_failure')
            self.assertIn('missing_batch:7',status['errors'])

    def test_old_batch_cannot_be_used_as_a_current_execution(self):
        merge_spec=importlib.util.spec_from_file_location('merge_current',Path(__file__).parents[1]/'forest/merge_batches.py')
        mm=importlib.util.module_from_spec(merge_spec);merge_spec.loader.exec_module(mm)
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);base=root/'in/forest-base';batch=root/'in/forest-shard-0'
            base.mkdir(parents=True);batch.mkdir()
            (base/'forest-status.json').write_text(json.dumps({'source_run_id':'current','status':'processed','errors':[]}))
            (base/'events.json').write_text(json.dumps({'a':{'status':'queued'}}))
            (batch/'forest-status.json').write_text(json.dumps({'source_run_id':'old','status':'processed','errors':[]}))
            (batch/'events.json').write_text(json.dumps({'a':{'status':'processed','last_attempt':'2026-01-03'}}))
            (batch/'old.png').write_bytes(b'old')
            mm.merge(root/'in',root/'out','current')
            result=json.loads((root/'out/events.json').read_text())
            state=json.loads((root/'out/forest-status.json').read_text())
            self.assertEqual(result['a']['status'],'queued')
            self.assertIn('stale_batch:forest-shard-0',state['errors'])
            self.assertFalse((root/'out/old.png').exists())
            with self.assertRaises(ValueError):mm.merge(root/'in',root/'wrong','different')
