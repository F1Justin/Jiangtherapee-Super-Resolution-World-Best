"""Check portable folding, refinement context and two-pass chunk reuse."""
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from weights import load_npz, weight_paths
from reconstruction_optimizations import fold_film, refinement_halo, install_chunk_reuse


def conv(source, weight, bias):
    radius = weight.shape[-1] // 2
    padded = np.pad(source, ((0, 0), (radius, radius), (radius, radius)))
    windows = np.lib.stride_tricks.sliding_window_view(padded, weight.shape[-2:], axis=(1, 2))
    return np.einsum('ihwkl,oikl->ohw', windows, weight, optimize=True) + bias[:, None, None]


class Optimizations(unittest.TestCase):
    def test_folding_real_weights_at_physical_edges(self):
        weights = load_npz(weight_paths(14)['refinenet'])
        self.compare_folding(weights)

    def test_folding_nonzero_projections(self):
        weights = load_npz(weight_paths(14)['refinenet'])
        rng = np.random.default_rng(43)
        for name, value in list(weights.items()):
            if name.startswith(('guide.', 'gammas.', 'betas.')):
                weights[name] = rng.normal(0, 0.03, value.shape).astype(np.float32)
        self.compare_folding(weights)

    def compare_folding(self, weights):
        before = {name: value.copy() for name, value in weights.items()}
        folded = fold_film(weights)
        source = np.random.default_rng(42).uniform(0, 1, (2, 11, 13)).astype(np.float32)
        guide = conv(source, weights['guide.weight'], weights['guide.bias'])
        for branch in ('gammas', 'betas'):
            for block in range(8):
                prefix = f'{branch}.{block}'
                expected = conv(guide, weights[prefix + '.weight'], weights[prefix + '.bias'])
                actual = conv(source, folded['folded_' + prefix + '.weight'], folded['folded_' + prefix + '.bias'])
                np.testing.assert_allclose(actual, expected, atol=1e-5, rtol=1e-5)
        for name in weights:
            np.testing.assert_array_equal(weights[name], before[name])

    def test_manifest_fallback(self):
        self.assertEqual(weight_paths(8)['refinenet'], weight_paths(14)['refinenet'])
        self.assertEqual(weight_paths(13)['controller'], weight_paths(14)['controller'])


    def test_refinement_context_contract(self):
        self.assertEqual(refinement_halo(24, 48, blocks=8, tta_codes=(0,)), 24)
        self.assertEqual(refinement_halo(48, 48, blocks=3, tta_codes=(1,)), 48)
        self.assertEqual(refinement_halo(24, 20, blocks=8, tta_codes=(0,)), 20)
        for halo, blocks, tta in ((16, 8, (0,)), (49, 8, (0,)), (24, 7, (0,)), (24, 8, (0, 1))):
            with self.assertRaises(ValueError):
                refinement_halo(halo, 48, blocks=blocks, tta_codes=tta)

    def test_chunk_replay_and_lifetime(self):
        class Reconstructor:
            calls = 0
            def _tile_chunks(self, source, *, warn):
                self.calls += 1
                yield source.copy()
            def merge_tile(self, source, changed=False, fail=False):
                first = list(self._tile_chunks(source, warn=True))
                second = list(self._tile_chunks(source.copy() if changed else source, warn=False))
                if fail:
                    raise RuntimeError('merge failure')
                return first, second
        install_chunk_reuse(Reconstructor)
        installed = Reconstructor.merge_tile
        install_chunk_reuse(Reconstructor)
        self.assertIs(installed, Reconstructor.merge_tile)
        instance = Reconstructor()
        source = np.arange(8, dtype=np.float32)
        first, second = instance.merge_tile(source)
        self.assertIs(first[0], second[0])
        self.assertEqual(instance.calls, 1)
        self.assertFalse(hasattr(instance, '_jsr_chunk_cache'))
        instance.merge_tile(source, changed=True)
        self.assertEqual(instance.calls, 3)
        with self.assertRaises(RuntimeError):
            instance.merge_tile(source, fail=True)
        self.assertFalse(hasattr(instance, '_jsr_chunk_cache'))
        list(instance._tile_chunks(source, warn=False))
        self.assertEqual(instance.calls, 5)

    def test_incomplete_phase_regenerates_chunks(self):
        class Reconstructor:
            calls = 0
            def _tile_chunks(self, *, warn):
                self.calls += 1
                yield np.zeros(1)
                yield np.ones(1)
            def merge_tile(self):
                phase = self._tile_chunks(warn=True)
                next(phase)
                replay = list(self._tile_chunks(warn=False))
                phase.close()
                return replay
        install_chunk_reuse(Reconstructor)
        instance = Reconstructor()
        self.assertEqual(len(instance.merge_tile()), 2)
        self.assertEqual(instance.calls, 2)


if __name__ == '__main__':
    unittest.main()
