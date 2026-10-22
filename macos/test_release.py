"""Calibration admission and incomplete-input regressions for standalone JSR."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from camera_calibration import resolve_ptc
from web_bridge import Bridge


def selection(count=14):
    return {'paths': [f'/fixture/{i}.nef' for i in range(count)], 'reference': 7,
        'width': 768, 'height': 768, 'white': 16383, 'black': 1008,
        'exposure_confirmation_required': False,
        'frames': [{'camera': 'NIKON Z 8', 'iso': 100, 'ev': 0, 'shutter': .001} for _ in range(count)]}


class ReleaseAdmission(unittest.TestCase):
    def test_ptc_interpolates_fullwell_not_gain(self):
        a = resolve_ptc({'camera': 'NIKON Z 8', 'iso': 50})
        b = resolve_ptc({'camera': 'NIKON Z 8', 'iso': 100})
        middle = resolve_ptc({'camera': 'NIKON Z 8', 'iso': 75})
        self.assertTrue(middle['matched'])
        self.assertAlmostEqual(middle['fullwell_e'], (a['fullwell_e'] + b['fullwell_e']) / 2)
        self.assertEqual(middle['selection'], 'linear_ISO_FWC')
        self.assertEqual(resolve_ptc({'camera': 'NIKON Z 8', 'iso': 25})['fullwell_e'], a['fullwell_e'])

    def test_unknown_camera_does_not_borrow_another_ptc(self):
        self.assertFalse(resolve_ptc({'camera': 'NIKON Z6_3', 'iso': 2000})['matched'])
        self.assertFalse(resolve_ptc({'camera': 'NIKON Z 8', 'iso': None})['matched'])

    def test_k14_rejects_missing_dark_even_with_manual_parameters(self):
        bridge = Bridge(); bridge.selected = selection()
        with tempfile.TemporaryDirectory() as output:
            with self.assertRaisesRegex(ValueError, 'K14.*黑场'):
                bridge.command({'engine': 'v98k14', 'output': output, 'prefix': 'test',
                    'manual': True, 'black': 1008, 'read_noise': 0, 'fullwell': 20000, 'dng': True})
            self.assertEqual(list(Path(output).iterdir()), [])

    def test_retired_preset_cannot_silently_reenable_calibration(self):
        bridge = Bridge(); bridge.selected = selection()
        with self.assertRaisesRegex(ValueError, '撤回'):
            bridge.command({'engine': 'fastk14', 'camera_preset': 'z8'})
        for route in ('jsr/camera-preset', 'jsr/batch-scan'):
            with self.assertRaisesRegex(ValueError, '撤回'):
                bridge.request(route, {})

    def test_partial_inputs_append_without_decoding_or_metadata(self):
        bridge = Bridge()
        with tempfile.TemporaryDirectory() as folder, patch('web_bridge.capture_metadata') as read:
            paths = [str(Path(folder) / f'{i}.dng') for i in range(3)]
            for p in paths: Path(p).touch()
            bridge.select({'paths': paths[:2], 'engine': 'stormer7', 'max_count': True})
            result = bridge.select({'paths': paths[1:], 'engine': 'stormer7', 'max_count': True, 'append': True})
            self.assertEqual(result['paths'], [str(Path(p).resolve()) for p in paths])
            self.assertNotIn('width', result)
            read.assert_not_called()


if __name__ == '__main__':
    unittest.main()
