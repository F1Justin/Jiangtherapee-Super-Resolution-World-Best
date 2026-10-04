"""Preserve the source camera orientation in exported files."""
from pathlib import Path
import hashlib
import json
import shutil
import subprocess


def snapshot_images(output: Path) -> dict[str, int]:
    return {str(p.resolve()): p.stat().st_mtime_ns for p in output.rglob('*')
            if p.is_file() and p.suffix.lower() in {'.dng', '.tif', '.tiff'}}


def preserve_orientation(output: Path, source: Path, initial_images=None) -> None:
    tool = shutil.which('exiftool')
    if not tool and Path('/opt/homebrew/bin/exiftool').is_file():
        tool = '/opt/homebrew/bin/exiftool'
    if not tool:
        raise RuntimeError('Install ExifTool to preserve camera orientation in exports')
    value = subprocess.check_output([tool, '-s3', '-n', '-Orientation', str(source)], text=True).strip()
    if value not in {str(i) for i in range(1, 9)}:
        return
    paths = [p for p in output.rglob('*') if p.suffix.lower() in {'.dng', '.tif', '.tiff'}]
    if initial_images is not None:
        paths = [p for p in paths if initial_images.get(str(p.resolve())) != p.stat().st_mtime_ns]
    if paths:
        subprocess.run([tool, '-overwrite_original_in_place', f'-Orientation#={value}', *map(str, paths)], check=True)
        fingerprints = {}
        for path in paths:
            digest = hashlib.sha256()
            with path.open('rb') as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                    digest.update(chunk)
            fingerprints[str(path.resolve())] = (path.stat().st_size, digest.hexdigest())

        def update(item):
            if isinstance(item, dict):
                path = item.get('path')
                if isinstance(path, str) and str(Path(path).resolve()) in fingerprints:
                    size, digest = fingerprints[str(Path(path).resolve())]
                    if 'bytes' in item:
                        item['bytes'] = size
                    if 'sha256' in item:
                        item['sha256'] = digest.upper()
                for child in item.values():
                    update(child)
                outputs = item.get('outputs', {})
                dng = outputs.get('dng') if isinstance(outputs, dict) else None
                if isinstance(dng, dict) and 'sha256' in dng and isinstance(outputs.get('compression'), dict):
                    outputs['compression']['output_sha256'] = dng['sha256']
            elif isinstance(item, list):
                for child in item:
                    update(child)

        for path in output.rglob('*.json'):
            report = json.loads(path.read_text())
            before = json.dumps(report, sort_keys=True)
            update(report)
            if json.dumps(report, sort_keys=True) != before:
                path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
