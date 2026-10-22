"""Capture metadata and camera/ISO matching against the upstream PTC table."""
from pathlib import Path
import bisect
import csv
import json
import re
import subprocess
from release import ROOT


def camera_key(value):
    return re.sub(r'[^a-z0-9]', '', str(value).lower()).replace('corporation', '')


def capture_metadata(paths):
    if not paths:
        return []
    return json.loads(subprocess.check_output(['exiftool', '-j', '-n', '-Make', '-Model', '-ISO',
        '-ExposureTime', '-FNumber', '-NEFCompression', '-DateTimeOriginal', '-SubSecTimeOriginal',
        '-OffsetTimeOriginal', *map(str, paths)], text=True))


def resolve_ptc(frame, index=None):
    iso = frame.get('iso')
    camera = camera_key(frame.get('camera', ''))
    if not iso or not camera:
        return {'matched': False}
    index = Path(index or ROOT / 'vendor/stormer/product_v152/ptc_index.csv')
    matches = []
    with index.open() as stream:
        for row in csv.DictReader(stream):
            keys = {camera_key(row['brand'] + row['model']), camera_key(row['model'])}
            if camera in keys and float(row['alpha']) > 0:
                matches.append(row)
    if not matches or len({r['sensor_id'] for r in matches}) != 1:
        return {'matched': False}
    values = {float(r['iso_nominal']): 1 / float(r['alpha']) for r in matches}
    levels = sorted(values)
    iso = float(iso)
    position = bisect.bisect_left(levels, iso)
    lo, hi = levels[max(0, position - 1)], levels[min(position, len(levels) - 1)]
    if iso in values:
        lo = hi = iso
    fraction = 0 if lo == hi else max(0, min(1, (iso - lo) / (hi - lo)))
    return {'matched': True, 'camera': matches[0]['brand'] + ' ' + matches[0]['model'].strip(),
        'iso': iso, 'fullwell_e': values[lo] * (1 - fraction) + values[hi] * fraction,
        'lower_iso': lo, 'upper_iso': hi,
        'selection': 'exact_ISO' if iso in values else 'endpoint' if iso < levels[0] or iso > levels[-1] else 'linear_ISO_FWC'}
