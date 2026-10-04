"""Check localized output validation gates."""
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'Core-Only-Source-Code'))
from compare_metal_outputs import compare_arrays


class OutputValidation(unittest.TestCase):
    def test_sparse_rounding_passes(self):
        reference = np.full((400, 400, 3), 512, np.uint16)
        candidate = reference.copy()
        candidate[10, 10, 0] += 1
        self.assertTrue(compare_arrays(reference, candidate, 64)['passed'])

    def test_localized_seam_error_fails(self):
        reference = np.full((400, 400, 3), 1000, np.uint16)
        candidate = reference.copy()
        candidate[:, 128] += 1
        result = compare_arrays(reference, candidate, 64)
        self.assertFalse(result['passed'])
        self.assertGreater(result['seam_rmse_dn'], 0.02)

    def test_large_local_error_fails(self):
        reference = np.full((400, 400, 3), 1000, np.uint16)
        candidate = reference.copy()
        candidate[10, 10] += 2
        self.assertFalse(compare_arrays(reference, candidate, 64)['passed'])


if __name__ == '__main__':
    unittest.main()
