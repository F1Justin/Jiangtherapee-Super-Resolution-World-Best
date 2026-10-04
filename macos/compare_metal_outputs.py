"""Compare full camera-linear DNG exports after native Metal optimization."""
from pathlib import Path
import argparse
import json

import numpy as np
import tifffile


def compare_arrays(reference, optimized, block_native=384):
    if reference.shape != optimized.shape or reference.dtype != optimized.dtype or reference.dtype != np.uint16:
        raise ValueError('Comparison requires matching uint16 RGB arrays')
    if reference.ndim != 3 or reference.shape[2] != 3 or block_native < 1:
        raise ValueError('Invalid RGB shape or tile size')
    maximum, changed, squares, dark_squares, dark_count, count = 0, 0, 0.0, 0.0, 0, 0
    seam_squares, seam_count, seam_maximum = 0.0, 0, 0
    signed_sum = np.zeros(3, np.float64)
    channel_squares = np.zeros(3, np.float64)
    step = block_native * 2
    columns = np.arange(reference.shape[1])
    xseam = (columns >= step - 2) & ((columns % step <= 2) | (columns % step >= step - 2))
    for row in range(0, reference.shape[0], 128):
        expected = reference[row:row + 128]
        delta = optimized[row:row + 128].astype(np.int32) - expected
        maximum = max(maximum, int(np.abs(delta).max()))
        changed += int(np.count_nonzero(delta))
        squared = delta.astype(np.float64) ** 2
        squares += float(squared.sum())
        signed_sum += delta.sum(axis=(0, 1), dtype=np.float64)
        channel_squares += squared.sum(axis=(0, 1))
        dark = expected < 655
        dark_squares += float(squared[dark].sum())
        dark_count += int(dark.sum())
        count += delta.size
        rows = np.arange(row, row + expected.shape[0])
        yseam = (rows >= step - 2) & ((rows % step <= 2) | (rows % step >= step - 2))
        seam = yseam[:, None] | xseam[None, :]
        if seam.any():
            seam_squares += float(squared[seam].sum())
            seam_count += int(seam.sum()) * 3
            seam_maximum = max(seam_maximum, int(np.abs(delta[seam]).max()))
    report = {'shape': list(reference.shape), 'dtype': str(reference.dtype), 'max_abs_dn': maximum,
              'rmse_dn': float(np.sqrt(squares / count)), 'changed_sample_fraction': changed / count,
              'channel_mean_signed_dn': (signed_sum / (count / 3)).tolist(),
              'channel_rmse_dn': np.sqrt(channel_squares / (count / 3)).tolist(),
              'dark_below_one_percent_rmse_dn': float(np.sqrt(dark_squares / dark_count)) if dark_count else None,
              'seam_rmse_dn': float(np.sqrt(seam_squares / seam_count)) if seam_count else None,
              'seam_max_abs_dn': seam_maximum, 'seam_band_output_pixels': 2, 'block_native': block_native,
              'gate': {'max_abs_dn_limit': 1, 'rmse_dn_limit': 0.02, 'dark_rmse_dn_limit': 0.02,
                       'seam_rmse_dn_limit': 0.02, 'channel_rmse_dn_limit': 0.02}}
    report['passed'] = maximum <= 1 and all(value is None or value <= 0.02 for value in
        [report['rmse_dn'], report['dark_below_one_percent_rmse_dn'], report['seam_rmse_dn'], *report['channel_rmse_dn']])
    return report


def raw_series(path):
    with tifffile.TiffFile(path) as image:
        return max((i for i, s in enumerate(image.series) if s.dtype == np.uint16 and s.shape[-1] == 3),
                   key=lambda i: np.prod(image.series[i].shape))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('reference', type=Path)
    parser.add_argument('optimized', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--block-native', type=int, default=384)
    args = parser.parse_args()
    reference = tifffile.memmap(args.reference, series=raw_series(args.reference))
    optimized = tifffile.memmap(args.optimized, series=raw_series(args.optimized))
    report = compare_arrays(reference, optimized, args.block_native)
    metadata = {}
    with tifffile.TiffFile(args.reference) as a, tifffile.TiffFile(args.optimized) as b:
        left_page, right_page = a.series[raw_series(args.reference)].pages[0], b.series[raw_series(args.optimized)].pages[0]
        for name in ('Orientation', 'BlackLevel', 'WhiteLevel', 'ColorMatrix1', 'AsShotNeutral', 'PhotometricInterpretation'):
            left = left_page.tags.get(name) or a.pages[0].tags.get(name)
            right = right_page.tags.get(name) or b.pages[0].tags.get(name)
            metadata[name] = bool(left is not None and right is not None and left.value == right.value)
    report['metadata_equal'] = metadata
    report['passed'] = report['passed'] and all(metadata.values())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    if not report['passed']:
        raise SystemExit('Native output parity gate failed')


if __name__ == '__main__':
    main()
