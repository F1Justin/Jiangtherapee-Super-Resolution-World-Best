"""Finalize compressed DNGs and preserve the actual reference capture metadata."""
from pathlib import Path
import json
import mmap
import struct
import subprocess
import sys
import tempfile
from release import ROOT, TAG

CAPTURE_TAGS = ('Make', 'Model', 'DateTimeOriginal', 'CreateDate', 'SubSecTimeOriginal',
    'SubSecTimeDigitized', 'OffsetTimeOriginal', 'OffsetTimeDigitized', 'ExposureTime',
    'FNumber', 'ISO', 'ExposureProgram', 'ExposureCompensation', 'MeteringMode', 'Flash',
    'FocalLength', 'FocalLengthIn35mmFormat', 'LensMake', 'LensModel', 'LensInfo', 'LensSerialNumber',
    'BodySerialNumber', 'Artist', 'Copyright', 'GPS:all')


def nikon_private_data(source):
    """Wrap an original Nikon MakerNote in Adobe's documented MakN directory."""
    private = subprocess.check_output(['exiftool', '-b', '-DNGPrivateData', str(source)])
    if private.startswith(b'Adobe\0'):
        return private
    with Path(source).open('rb') as stream:
        if stream.read(4) not in (b'II*\0', b'MM\0*'):
            return b''
    import tifffile
    with tifffile.TiffFile(source) as tif:
        exif = tif.pages[0].tags.get('ExifTag')
        note = exif.value.get('MakerNote', b'') if exif else b''
    if not note.startswith(b'Nikon\0'):
        return b''
    with Path(source).open('rb') as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
        offset = data.find(note)
        order = data[:2]
    if offset < 0 or order not in (b'II', b'MM'):
        raise ValueError('Cannot locate original Nikon MakerNotes')
    body = order + struct.pack('>I', offset) + note
    return b'Adobe\0MakN' + struct.pack('>I', len(body)) + body + (b'\0' if len(body) % 2 else b'')


def reference_for(output, frames, mode):
    if mode == 'stormer':
        for path in output.rglob('camera_linear.json'):
            sources = json.loads(path.read_text()).get('frame_order', {}).get('model_sources', [])
            if sources:
                return Path(sources[0])
    if mode == 'fast':
        report = output / 'RESULT.json'
        if report.exists():
            source = json.loads(report.read_text()).get('reference')
            if source:
                return Path(source)
    if mode == 'v98':
        for path in output.glob('*PRODUCT.json'):
            index = json.loads(path.read_text()).get('selection', {}).get('reference_index')
            if isinstance(index, int) and 0 <= index < len(frames):
                return Path(frames[index])
    return Path(frames[len(frames)//2])


def preserve_capture(paths, source):
    import tifffile
    private = nikon_private_data(source)
    records = []
    with tempfile.TemporaryDirectory(prefix='jsr-metadata-') as temporary:
        note = Path(temporary) / 'private.bin'
        note.write_bytes(private)
        for path in paths:
            with tifffile.TiffFile(path) as tif:
                pages = list(tif.pages)
                for page in list(pages):
                    if page.pages:
                        pages.extend(page.pages)
                raw = max(pages, key=lambda p: p.imagewidth * p.imagelength)
                width, height = raw.imagewidth, raw.imagelength
            command = ['exiftool', '-overwrite_original_in_place', '-TagsFromFile', str(source)]
            command += ['-' + tag for tag in CAPTURE_TAGS]
            command += [f'-ExifImageWidth={width}', f'-ExifImageHeight={height}']
            if private:
                command += ['-DNGPrivateData<=' + str(note)]
            subprocess.run([*command, str(path)], check=True)
            records.append({'path': str(path), 'reference': str(source), 'nikon_private_data': bool(private),
                            'exif_dimensions': [width, height]})
    return records


def finalize(output, frames, mode, initial_images=None, compress=True):
    output = Path(output)
    initial_images = initial_images or {}
    paths = [p for p in output.rglob('*.dng') if initial_images.get(str(p.resolve())) != p.stat().st_mtime_ns]
    if not paths:
        return
    if mode == 'v98' and compress:
        print('SRHQ_V12_PROGRESS|98|DNG 无损压缩', flush=True)
        # A separate interpreter avoids mixing Stormer and v9.8 module names.
        runner = ROOT / 'run_stormer.py'
        if not runner.exists():
            runner = runner.with_suffix('.pyc')
        for path in paths:
            subprocess.run([sys.executable, str(runner), '--compress-existing-dng', str(path)], check=True)
    source = reference_for(output, frames, mode)
    print('SRHQ_V12_PROGRESS|99|写入参考帧 EXIF', flush=True)
    records = preserve_capture(paths, source)
    from finish import preserve_orientation
    preserve_orientation(output, source, initial_images)
    (output / 'CAPTURE_EXPORT.json').write_text(json.dumps({'release': TAG, 'reference': str(source),
        'outputs': records}, ensure_ascii=False, indent=2))
