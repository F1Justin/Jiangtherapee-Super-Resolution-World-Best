"""Build the published Nikon HE LibRaw decoder and a native Bridge ABI shim."""
from pathlib import Path
import hashlib
import importlib.util
import os
import shutil
import subprocess
import sys
import tarfile
import zipfile
from release import LIBRAW_SOURCE_NAME, LIBRAW_SOURCE_SHA256, sha256, extract_shared, ARCHIVE_NAME

ROOT = Path(__file__).resolve().parent
VENDOR = ROOT / 'vendor'
SOURCES = [
    ('LibRaw-base.tar.gz', 'https://codeload.github.com/LibRaw/LibRaw/tar.gz/b93f6e45c194f5df9b02a43b1af9a54b4f41f33f', '95df0a1e14ada99595632ca4556082fe4653cf74ce21ebdfb2f1d8729cab323d'),
    ('libraw-cmake.tar.gz', 'https://codeload.github.com/LibRaw/LibRaw-cmake/tar.gz/6e26c9e73677dc04f9eb236a97c6a4dc225ba7e8', 'd0ecc870bb395ca05d4de61314d092437bb37afac1e17131cc64c58e57369a11'),
]


def run(args, **kwargs):
    subprocess.run(list(map(str, args)), check=True, **kwargs)


def main():
    VENDOR.mkdir(exist_ok=True)
    source = VENDOR / 'libraw-source'
    archive = VENDOR / LIBRAW_SOURCE_NAME
    if not archive.exists():
        extract_shared(VENDOR / ARCHIVE_NAME)
    if sha256(archive) != LIBRAW_SOURCE_SHA256:
        raise SystemExit('Official LibRaw source archive checksum mismatch')
    name, url, expected = SOURCES[1]
    cmake_archive = VENDOR / name
    if not cmake_archive.exists():
        run(['curl', '-fLsS', '--retry', '3', '-o', cmake_archive, url])
    if sha256(cmake_archive) != expected:
        raise SystemExit('LibRaw CMake checksum mismatch')
    marker = source / '.jsr-patched'
    if not marker.exists() or marker.read_text().strip() != LIBRAW_SOURCE_SHA256:
        if source.exists():
            shutil.rmtree(source)
        source.mkdir()
        with zipfile.ZipFile(archive) as package:
            for entry in package.namelist():
                if not entry.startswith('LibRaw-0.22.2/') or entry.endswith('/'):
                    continue
                relative = Path(entry).relative_to('LibRaw-0.22.2')
                if '..' in relative.parts:
                    raise ValueError('Unsafe source path')
                target = source / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(package.read(entry))
        with tarfile.open(cmake_archive) as package:
            for member in package.getmembers():
                member.name = '/'.join(member.name.split('/')[1:])
                if member.name:
                    package.extract(member, source, filter='data')
        marker.write_text(LIBRAW_SOURCE_SHA256 + '\n')
    build = VENDOR / 'libraw-build'
    prefix = VENDOR / 'libraw'
    brew = subprocess.check_output(['brew', '--prefix'], text=True).strip()
    run(['cmake', '-S', source, '-B', build, '-G', 'Ninja', '-DCMAKE_BUILD_TYPE=Release',
         '-DCMAKE_OSX_ARCHITECTURES=arm64', '-DENABLE_OPENMP=OFF', '-DENABLE_JASPER=OFF',
         '-DENABLE_EXAMPLES=OFF', f'-DCMAKE_PREFIX_PATH={brew}', f'-DCMAKE_INSTALL_PREFIX={prefix}'])
    run(['cmake', '--build', build, '--target', 'raw_r', '-j', '6'])
    lib = prefix / 'lib'
    lib.mkdir(parents=True, exist_ok=True)
    target = lib / 'libraw_r.25.0.0.dylib'
    shutil.copyfile(build / target.name, target)
    run(['install_name_tool', '-id', lib / 'libraw_r.25.dylib', target])
    run(['codesign', '--force', '--sign', '-', target])
    for name in ['libraw_r.25.dylib', 'libraw_r.dylib']:
        destination = lib / name
        if destination.is_symlink():
            destination.unlink()
        shutil.copyfile(target, destination)
    run(['clang++', '-std=c++17', '-O2', '-arch', 'arm64', '-dynamiclib', ROOT / 'native/raw_bridge.cpp',
         '-I', source, '-L', lib, '-lraw_r', f'-Wl,-rpath,{lib}', '-o', lib / 'jsr_raw_bridge.dylib'])
    package = Path(importlib.util.find_spec('rawpy').origin).parent
    for name in ['libraw_r.25.0.0.dylib', 'libraw_r.25.dylib', 'libraw_r.dylib']:
        staging = package / (name + '.new')
        shutil.copyfile(target, staging)
        os.replace(staging, package / name)
    print('Native Nikon HE decoder and RAW bridge installed; restart Python to load them.')


if __name__ == '__main__':
    main()
