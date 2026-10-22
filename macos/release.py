"""Verified upstream baseline shared by extraction, runtime and packaging."""
from pathlib import Path
import hashlib
import zipfile

UPSTREAM_VERSION = '17.3.1'
VERSION = UPSTREAM_VERSION + '-macos.1'
TAG = 'jsr-v' + UPSTREAM_VERSION
ARCHIVE_NAME = f'JSR_V{UPSTREAM_VERSION}.zip'
ARCHIVE_SHA256 = '3509347135e2513b95104fa545da2479fdf23262aa26135249b245075cd7fef5'
UI_EXECUTABLE = f'JSR_V{UPSTREAM_VERSION}.exe'
PREFIX = ARCHIVE_NAME.removesuffix('.zip') + '/'
LIBRAW_SOURCE_NAME = 'LibRaw_HE_Fixes_20261007.zip'
LIBRAW_SOURCE_SHA256 = '7e7bb2dc8f54098c0b488572cfd6adea4adf29d162353b3f0c155a2b1f1fdc94'
LIBRAW_SOURCE_RELEASE = 'jb-v2.3.27'
LIBRAW_SOURCE_ARCHIVE = 'Jiangtherapee-Bridge-2.3.27-Windows-x64.zip'
LIBRAW_SOURCE_ARCHIVE_SHA256 = '70c16b20cdaa03530ba220ccbc4d597d8429e781b522b0e8e086f00fb421aec9'
ROOT = Path(__file__).resolve().parent


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def verified_archive(path=None):
    path = Path(path) if path else ROOT / 'vendor' / ARCHIVE_NAME
    if sha256(path) != ARCHIVE_SHA256:
        raise ValueError(f'Official {UPSTREAM_VERSION} archive checksum mismatch')
    return zipfile.ZipFile(path)


def extract_shared(path):
    """Stage camera presets and third-party source from the verified package."""
    with verified_archive(path) as package:
        for name in package.namelist():
            relative = name.removeprefix(PREFIX)
            if name.endswith('/'):
                continue
            if relative.startswith('resources/licenses/'):
                target = ROOT / 'vendor' / relative.removeprefix('resources/')
            elif relative in ('resources/jsr_backend_manifest.json', 'resources/jsr_options.json'):
                target = ROOT / 'vendor' / relative.removeprefix('resources/')
            elif relative == 'ThirdPartySources/' + LIBRAW_SOURCE_NAME:
                target = ROOT / 'vendor' / LIBRAW_SOURCE_NAME
            else:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(package.read(name))


def ensure_libraw_source():
    """17.3.1 uses the same decoder; its source remains in the pinned Bridge release."""
    target = ROOT / 'vendor' / LIBRAW_SOURCE_NAME
    if target.exists() and sha256(target) == LIBRAW_SOURCE_SHA256:
        return target
    archive = ROOT / 'vendor' / LIBRAW_SOURCE_ARCHIVE
    if not archive.exists() or sha256(archive) != LIBRAW_SOURCE_ARCHIVE_SHA256:
        raise RuntimeError('Place the verified ' + LIBRAW_SOURCE_ARCHIVE + ' in macos/vendor for LibRaw source')
    with zipfile.ZipFile(archive) as package:
        data = package.read(archive.stem + '/ThirdPartySources/' + LIBRAW_SOURCE_NAME)
    if hashlib.sha256(data).hexdigest() != LIBRAW_SOURCE_SHA256:
        raise ValueError('LibRaw source checksum mismatch')
    target.write_bytes(data)
    return target
