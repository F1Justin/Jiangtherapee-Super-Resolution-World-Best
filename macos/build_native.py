"""Build the published Nikon HE LibRaw decoder and a native Bridge ABI shim."""
from pathlib import Path
import hashlib
import importlib.util
import os
import shutil
import subprocess
import sys
import tarfile

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
    for name, url, expected in SOURCES:
        archive = VENDOR / name
        if not archive.exists():
            run(['curl', '-fLsS', '--retry', '3', '--retry-all-errors', '-o', archive, url])
        if hashlib.sha256(archive.read_bytes()).hexdigest() != expected:
            raise SystemExit(f'Source archive checksum mismatch: {name}')
    if not (source / '.jsr-patched').exists():
        if source.exists():
            shutil.rmtree(source)
        source.mkdir()
        for name, _, _ in SOURCES:
            with tarfile.open(VENDOR / name) as archive:
                for member in archive.getmembers():
                    member.name = '/'.join(member.name.split('/')[1:])
                    if member.name:
                        archive.extract(member, source, filter='data')
        patch_bytes = (ROOT.parent / 'Third-Party-Licenses/LibRaw/libraw-0.22.2-nikon-he.patch').read_bytes()
        if hashlib.sha256(patch_bytes).hexdigest() != '633864efc205602e906e986f9cdb3bc1302a7d3e504ca452312dcc729222b17c':
            raise SystemExit('Nikon HE patch checksum mismatch')
        patch = patch_bytes.decode()
        # The supplied qmake hunk targets a different .pro layout; CMake recursively finds the decoder sources.
        sections = patch.split('diff --git ')
        applicable = ''.join('diff --git ' + part for part in sections[1:] if not part.startswith('a/buildfiles/libraw.pro '))
        run(['patch', '-d', source, '-p1'], input=applicable, text=True)
        (source / '.jsr-patched').write_text('LibRaw 0.22.2 + Nikon HE 499bfd4; CMake arm64\n')
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
