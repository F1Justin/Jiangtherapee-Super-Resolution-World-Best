"""Resolve the official Z8 empirical dark library independently for each burst."""
from pathlib import Path
import bisect
import csv
import json
import re
import subprocess
from release import ROOT, sha256


def camera_key(value):
    return re.sub(r'[^a-z0-9]', '', str(value).lower()).removeprefix('nikoncorporation').removeprefix('nikon')


def capture_metadata(paths):
    if not paths:
        return []
    return json.loads(subprocess.check_output(['exiftool', '-j', '-n', '-Make', '-Model', '-ISO',
        '-ExposureTime', '-FNumber', '-NEFCompression', '-DateTimeOriginal', '-SubSecTimeOriginal',
        '-OffsetTimeOriginal', *map(str, paths)], text=True))


def resolve_z8(selected, library=None, ptc=None):
    library = Path(library or ROOT / 'vendor/z8_presets')
    ptc = Path(ptc or ROOT / 'vendor/stormer/product_v152/ptc_index.csv')
    frames = selected.get('frames', [])
    if not frames or any(camera_key(f.get('camera', '')) != 'z8' for f in frames):
        raise ValueError('Z8 内置黑场仅适用于 Nikon Z8 原片')
    reference = selected.get('reference', 0)
    frame = frames[reference]
    iso = float(frame.get('iso') or 100)
    modes = {3: 0, 14: 3, 13: 4}  # ExifTool NEFCompression -> upstream preset mode.
    compression = modes.get(frame.get('nef_compression'), 0)
    rows = json.loads((library / 'manifest.json').read_text())['profiles']
    candidates = [r for r in rows if r['compression'] == compression]
    profile = min(candidates, key=lambda r: (abs(r['iso'] - iso), r['iso']))
    dark = library / profile['dark_file']
    if sha256(dark) != profile['dark_sha256'].lower():
        raise RuntimeError('Z8 黑场校验失败：' + dark.name)
    values = {}
    with ptc.open() as stream:
        for row in csv.DictReader(stream):
            if camera_key(row['brand'] + row['model']) == 'z8' and float(row['alpha']) > 0:
                values[float(row['iso_nominal'])] = 1 / float(row['alpha'])
    levels = sorted(values)
    if not levels:
        raise RuntimeError('Z8 PTC 表缺失')
    position = bisect.bisect_left(levels, iso)
    lower = levels[max(0, position - 1)]
    upper = levels[min(position, len(levels) - 1)]
    if iso in values:
        lower = upper = iso
    fraction = 0 if upper == lower else max(0, min(1, (iso - lower) / (upper - lower)))
    fullwell = values[lower] * (1 - fraction) + values[upper] * fraction
    return {'active': True, 'camera': 'Nikon Z8', 'iso': iso, 'compression': compression,
        'dark': str(dark.resolve()), 'dark_sha256': profile['dark_sha256'], 'preset_iso': profile['iso'],
        'fullwell_e': fullwell, 'interpolation': {'lower_iso': lower, 'upper_iso': upper, 'fraction': fraction},
        'fallback': {'missing_iso': not frame.get('iso'), 'missing_compression': frame.get('nef_compression') not in modes,
                     'nearest_dark_iso': profile['iso'] != iso, 'ptc_endpoint': iso < levels[0] or iso > levels[-1]},
        'reference': selected['paths'][reference],
        'label': f"Nikon Z8 · {profile['compression_name']} · ISO {iso:g} · 内置黑场 ISO {profile['iso']}"}
