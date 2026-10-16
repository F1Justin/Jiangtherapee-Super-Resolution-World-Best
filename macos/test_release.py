"""Regression checks for per-burst calibration and immutable batch selections."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from batch_workflow import group_records
from camera_presets import resolve_z8
from web_bridge import Bridge


def selection(iso=100, compression=3, camera='NIKON Z 8', count=14):
    return {'paths': [f'/fixture/{iso}-{i}.nef' for i in range(count)], 'reference': 6,
        'width': 8280, 'height': 5520, 'white': 16383, 'black': 1008,
        'exposure_confirmation_required': False,
        'frames': [{'camera': camera, 'iso': iso, 'nef_compression': compression, 'ev': 0, 'shutter': .001} for _ in range(count)]}


class Presets(unittest.TestCase):
    def test_modes_and_interpolation(self):
        a = resolve_z8(selection(50))
        b = resolve_z8(selection(100))
        middle = resolve_z8(selection(75, 14))
        self.assertAlmostEqual(middle['fullwell_e'], (a['fullwell_e'] + b['fullwell_e']) / 2)
        self.assertEqual(middle['compression'], 3)
        self.assertEqual(resolve_z8(selection(100, 13))['compression'], 4)
        self.assertEqual(resolve_z8(selection(32))['fullwell_e'], a['fullwell_e'])
        self.assertNotEqual(resolve_z8(selection(2000))['dark'], b['dark'])

    def test_reject_other_camera(self):
        with self.assertRaisesRegex(ValueError, 'Z8'):
            resolve_z8(selection(camera='NIKON Z6_3'))

    def test_batch_uses_saved_group_not_last_preview(self):
        bridge = Bridge()
        bridge.selections = {'first': selection(100), 'second': selection(2000)}
        bridge.selected = bridge.selections['second']
        with tempfile.TemporaryDirectory() as output:
            p = {'engine': 'fastk14', 'selection_id': 'first', 'camera_preset': 'z8',
                 'output': output, 'prefix': 'test', 'dng': True}
            command, _ = bridge.command(p)
            self.assertIn('/fixture/100-0.nef', command)
            self.assertNotIn('/fixture/2000-0.nef', command)
            self.assertEqual(bridge.preset['iso'], 100)
            p['selection_id'] = 'second'
            command, _ = bridge.command(p)
            self.assertIn('/fixture/2000-0.nef', command)
            self.assertEqual(bridge.preset['iso'], 2000)
            bridge.request('jsr/batch-clear-selections', {})
            with self.assertRaisesRegex(ValueError, '过期'):
                bridge.command(p)

    def test_capture_groups_never_use_copy_time(self):
        records = [{'path': str(i), 'name': str(i), 'camera': 'NIKON Z 8', 'camera_key': 'z8',
                    'timestamp': 100 + i * .1} for i in range(14)]
        records += [{**r, 'path': 'second-'+r['path'], 'timestamp': r['timestamp'] + 20} for r in records]
        records += [{'path': 'unknown', 'name': 'unknown', 'camera': 'NIKON Z 8', 'camera_key': 'z8', 'timestamp': 0}]
        result = group_records(records, 14)
        self.assertEqual([len(g['selected']) for g in result['groups']], [14, 14])
        self.assertEqual(result['ungrouped'][0]['path'], 'unknown')


if __name__ == '__main__':
    unittest.main()
