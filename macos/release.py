"""Verified upstream baseline shared by extraction, runtime and packaging."""
from pathlib import Path
import hashlib
import zipfile

UPSTREAM_VERSION = '2.3.27'
VERSION = UPSTREAM_VERSION + '-macos.1'
TAG = 'jb-v' + UPSTREAM_VERSION
ARCHIVE_NAME = f'Jiangtherapee-Bridge-{UPSTREAM_VERSION}-Windows-x64.zip'
ARCHIVE_SHA256 = '70c16b20cdaa03530ba220ccbc4d597d8429e781b522b0e8e086f00fb421aec9'
PREFIX = ARCHIVE_NAME.removesuffix('.zip') + '/'
LIBRAW_SOURCE_NAME = 'LibRaw_HE_Fixes_20261007.zip'
LIBRAW_SOURCE_SHA256 = '7e7bb2dc8f54098c0b488572cfd6adea4adf29d162353b3f0c155a2b1f1fdc94'
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
            if relative.startswith('resources/z8_presets/') or relative.startswith('resources/licenses/'):
                target = ROOT / 'vendor' / relative.removeprefix('resources/')
            elif relative in ('resources/jsr_backend_manifest.json', 'resources/jsr_options.json'):
                target = ROOT / 'vendor' / relative.removeprefix('resources/')
            elif relative == 'ThirdPartySources/' + LIBRAW_SOURCE_NAME:
                target = ROOT / 'vendor' / LIBRAW_SOURCE_NAME
            else:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(package.read(name))
