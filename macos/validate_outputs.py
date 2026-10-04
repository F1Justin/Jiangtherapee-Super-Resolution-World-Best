"""Read back native DNG exports and verify matching camera-linear TIFF pixels."""
from pathlib import Path
import argparse
import json

import numpy as np
import rawpy
import tifffile
from PIL import Image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    rows = []
    for dng in sorted(args.output.rglob('*.dng')):
        with tifffile.TiffFile(dng) as image:
            page = image.pages[0].pages[0] if image.pages[0].pages else image.pages[0]
            pixels = page.asarray()
            row = {'dng': str(dng.resolve()), 'shape': list(pixels.shape),
                   'dtype': str(pixels.dtype), 'compression': int(page.compression)}
        assert pixels.dtype == np.uint16 and pixels.ndim == 3 and pixels.shape[2] == 3
        candidates = [dng.with_suffix('.tiff'), *dng.parent.rglob(dng.stem + '_linear_u16.tiff')]
        linear_tiff = next((p for p in candidates if p.is_file()), None)
        if linear_tiff:
            tiff_pixels = tifffile.imread(linear_tiff)
            row['linear_tiff'] = str(linear_tiff.resolve())
            row['dng_tiff_pixels_equal'] = bool(np.array_equal(pixels, tiff_pixels))
            assert row['dng_tiff_pixels_equal']
            del tiff_pixels
        with rawpy.imread(str(dng)) as decoded:
            # LibRaw stores LinearRaw RGB outside raw_image_visible; validate its processed RGB API.
            readback = decoded.postprocess(use_camera_wb=True, output_bps=16)
            expected_shape = (pixels.shape[1], pixels.shape[0], 3) if decoded.sizes.flip in (5, 6) else pixels.shape
            assert readback.shape == expected_shape and readback.dtype == np.uint16
            assert np.any(readback)
            row['libraw_render'] = {'shape': list(readback.shape), 'dtype': str(readback.dtype),
                                    'minimum': int(readback.min()), 'maximum': int(readback.max()),
                                    'orientation_flip': decoded.sizes.flip}
            preview = Image.fromarray((readback >> 8).astype(np.uint8))
            preview.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
            preview.save(dng.with_suffix('.jpg'))
            del readback
        del pixels
        rows.append(row)
    if not rows:
        raise SystemExit('No DNG exports found')
    for tiff in args.output.rglob('*.tiff'):
        with tifffile.TiffFile(tiff) as image:
            assert image.pages[0].dtype == np.dtype('uint16')
    (args.output / 'pixel-validation.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2))
    print(json.dumps({'verified_dng_files': len(rows), 'outputs': rows}, ensure_ascii=False))


if __name__ == '__main__':
    main()
