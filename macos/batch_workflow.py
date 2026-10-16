"""Local capture-time grouping for the upstream Z8 batch UI."""
from datetime import datetime
from pathlib import Path
from camera_presets import capture_metadata, camera_key


def group_records(records, count):
    groups, ungrouped, runs = [], [], []
    for record in sorted(records, key=lambda r: (r.get('timestamp', 0), r['path'])):
        if not record.get('timestamp'):
            ungrouped.append({**record, 'reason': '缺少有效拍摄时间'})
            continue
        if camera_key(record.get('camera', '')) != 'z8':
            ungrouped.append({**record, 'reason': '当前批量仅支持 Nikon Z8'})
            continue
        if not runs or record['camera_key'] != runs[-1][-1]['camera_key'] or record['timestamp'] - runs[-1][-1]['timestamp'] > 5:
            runs.append([])
        runs[-1].append(record)
    for run in runs:
        if len(run) < count:
            ungrouped.extend({**r, 'reason': f'连续组不足 {count} 张'} for r in run)
            continue
        groups.append({'id': f'group-{len(groups)+1:03d}', 'camera': run[0]['camera'],
            'camera_key': run[0]['camera_key'], 'start': run[0]['timestamp'], 'photos': run,
            'selected': [r['path'] for r in run[:count]]})
    return {'groups': groups, 'ungrouped': ungrouped}


def scan(folder, recursive, count, extensions):
    folder = Path(folder).expanduser().resolve(strict=True)
    if not folder.is_dir():
        raise ValueError('请选择 RAW 目录')
    paths = sorted(p for p in (folder.rglob('*') if recursive else folder.iterdir())
                   if p.is_file() and p.suffix.lower() in extensions)
    records = []
    for start in range(0, len(paths), 100):
        chunk = paths[start:start+100]
        for path, row in zip(chunk, capture_metadata(chunk)):
            date = str(row.get('DateTimeOriginal') or '')
            subsec = str(row.get('SubSecTimeOriginal') or '')
            try:
                parsed = datetime.strptime(date, '%Y:%m:%d %H:%M:%S')
                offset = str(row.get('OffsetTimeOriginal') or '')
                if offset:
                    parsed = datetime.fromisoformat(parsed.isoformat() + offset)
                stamp = parsed.timestamp() + (float('0.' + subsec) if subsec.isdigit() else 0)
            except ValueError:
                stamp = 0
            records.append({'path': str(path), 'name': path.name, 'camera': row.get('Model', ''),
                'camera_key': camera_key(row.get('Model', '')), 'make': row.get('Make', ''), 'model': row.get('Model', ''),
                'iso': row.get('ISO'), 'shutter': row.get('ExposureTime'), 'aperture': row.get('FNumber'),
                'timestamp': stamp, 'capture_time': date, 'capture_subsec': subsec})
    return {'folder': str(folder), **group_records(records, count)}
