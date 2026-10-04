"""Build a relocatable arm64 runtime with GUI and CLI entry points."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import plistlib
import py_compile
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
VERSION = '2.3.9-macos-preview.1'
MODULES = ('portable_cli', 'gui', 'run_fast', 'run_stormer', 'run_v98', 'finish',
           'job_resources', 'metal_graph', 'metal_platform', 'native_fusion',
           'optimization_support', 'refine_schedule', 'check_native_fusion')
MACH_MAGIC = (b'\xcf\xfa\xed\xfe', b'\xfe\xed\xfa\xcf', b'\xca\xfe\xba\xbe', b'\xbe\xba\xfe\xca')


def run(args):
    return subprocess.check_output(list(map(str, args)), text=True, stderr=subprocess.STDOUT)


def compile_module(source, destination, label):
    destination.parent.mkdir(parents=True, exist_ok=True)
    py_compile.compile(str(source), cfile=str(destination), dfile=label, doraise=True)


def mach_files(root):
    for path in sorted(root.rglob('*')):
        if path.is_file() and not path.is_symlink():
            with path.open('rb') as stream:
                if stream.read(4) in MACH_MAGIC:
                    yield path


def relocate(resources, source_prefixes):
    external = resources / 'runtime/lib/jsr-deps'
    external.mkdir(parents=True, exist_ok=True)
    pending = list(mach_files(resources))
    checked, copied, external_names = set(), {}, {}
    while pending:
        path = pending.pop()
        if path in checked:
            continue
        checked.add(path)
        arch = run(['lipo', '-archs', path]).split()
        if 'arm64' not in arch:
            raise RuntimeError(f'Non-arm64 binary: {path}')
        lines = run(['otool', '-L', path]).splitlines()[1:]
        identity = run(['otool', '-D', path]).splitlines()[1:]
        for line in lines:
            if not line.startswith('\t'):
                continue
            dependency = line.strip().split(' (compatibility')[0]
            if dependency in identity:
                continue
            if not dependency.startswith('/') or dependency.startswith(('/usr/lib/', '/System/Library/')):
                continue
            original = Path(dependency)
            target = None
            for source, destination in source_prefixes:
                if original.is_relative_to(source):
                    candidate = destination / original.relative_to(source)
                    if candidate.exists():
                        target = candidate
                        break
            if target is None:
                resolved = original.resolve(strict=True)
                target = copied.get(resolved)
                if target is None:
                    target = external / resolved.name
                    if target.name in external_names and external_names[target.name] != resolved:
                        raise RuntimeError(f'Dependency filename collision: {target.name}')
                    external_names[target.name] = resolved
                    shutil.copy2(resolved, target)
                    copied[resolved] = target
                    pending.append(target)
            replacement = '@loader_path/' + os.path.relpath(target, path.parent)
            run(['install_name_tool', '-change', dependency, replacement, path])
        load_commands = run(['otool', '-l', path]).splitlines()
        for index, line in enumerate(load_commands):
            if line.strip() == 'cmd LC_RPATH':
                old = load_commands[index + 2].strip().split('path ', 1)[1].split(' (offset')[0]
                if old.startswith('/') and not old.startswith(('/usr/lib/', '/System/Library/')):
                    run(['install_name_tool', '-delete_rpath', old, path])
        if path.suffix == '.dylib':
            run(['install_name_tool', '-id', '@rpath/' + path.name, path])
        run(['codesign', '--force', '--sign', '-', path])
    unresolved = []
    for path in sorted(checked):
        for line in run(['otool', '-L', path]).splitlines()[1:]:
            if not line.startswith('\t'):
                continue
            dependency = line.strip().split(' (compatibility')[0]
            if dependency.startswith('/') and not dependency.startswith(('/usr/lib/', '/System/Library/')):
                unresolved.append((str(path.relative_to(resources)), dependency))
            elif dependency.startswith('@loader_path/'):
                target = path.parent / dependency.removeprefix('@loader_path/')
                if not target.exists():
                    unresolved.append((str(path.relative_to(resources)), dependency))
    if unresolved:
        raise RuntimeError(f'Unresolved dynamic dependencies: {unresolved}')
    return {'mach_o_files': len(checked), 'external_libraries_bundled': sorted(p.name for p in external.iterdir()),
            'unresolved_absolute_dependencies': unresolved}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'dist' / ('JSR-Bridge-' + VERSION + '-macOS-arm64-portable'))
    parser.add_argument('--resume', action='store_true', help='Reuse copied payload and rebuild launch metadata')
    args = parser.parse_args()
    if sys.version_info[:2] != (3, 10):
        raise SystemExit('Build with macos/.venv/bin/python')
    output = args.output.resolve()
    if output.exists() and not args.resume:
        raise SystemExit('Use a fresh build directory')
    app = output / 'JSR Bridge.app'
    contents = app / 'Contents'
    resources = contents / 'Resources'
    engine = resources / 'engine'
    runtime = resources / 'runtime'
    base = Path(sys.base_prefix)
    site = Path(sys.prefix) / 'lib/python3.10/site-packages'
    bundled_site = runtime / 'lib/python3.10/site-packages'
    vendor = engine / 'vendor'
    if not args.resume:
        engine.mkdir(parents=True)
        print('Copying Python and runtime packages', flush=True)
        base = Path(sys.base_prefix)
        shutil.copytree(base, runtime, symlinks=True, ignore=shutil.ignore_patterns('__pycache__', '*.a', 'test', 'tests', 'idlelib', 'ensurepip'))
        site = Path(sys.prefix) / 'lib/python3.10/site-packages'
        bundled_site = runtime / 'lib/python3.10/site-packages'
        shutil.copytree(site, bundled_site, dirs_exist_ok=True, symlinks=True,
                        ignore=shutil.ignore_patterns('__pycache__', 'PyInstaller', '_pyinstaller_hooks_contrib', 'pip', 'pip-*', 'altgraph*', 'pyinstaller*'))
        for path in (runtime / 'bin').iterdir():
            if path.name not in ('python', 'python3', 'python3.10'):
                path.unlink()
        shutil.rmtree(runtime / 'include', ignore_errors=True)
        shutil.rmtree(runtime / 'share', ignore_errors=True)
        for name in MODULES:
            compile_module(ROOT / (name + '.py'), engine / (name + '.pyc'), 'engine/' + name + '.py')
        print('Copying original release resources', flush=True)
        vendor = engine / 'vendor'
        for mode in ('fast', 'stormer', 'v98'):
            shutil.copytree(ROOT / 'vendor' / mode, vendor / mode,
                            ignore=shutil.ignore_patterns('__pycache__', '*.exe', '*.dll', '*.py', 'manifest.json'))
            for source in (ROOT / 'vendor' / mode).rglob('*.py'):
                target = vendor / mode / source.relative_to(ROOT / 'vendor' / mode)
                # Release modules address these tiny bytecode loaders by their .py names.
                shutil.copy2(source, target)
        rawlib = vendor / 'libraw/lib'
        rawlib.mkdir(parents=True)
        for name in ('jsr_raw_bridge.dylib', 'libraw_r.25.dylib'):
            shutil.copy2(ROOT / 'vendor/libraw/lib' / name, rawlib / name)
        core = resources / 'Core-Only-Source-Code'
        core.mkdir()
        for source in (ROOT.parent / 'Core-Only-Source-Code').glob('*.py'):
            compile_module(source, core / source.with_suffix('.pyc').name, 'core/' + source.name)
        shutil.copytree(ROOT.parent / 'Core-Only-Source-Code/weights', core / 'weights')
        tools = resources / 'tools'
        tools.mkdir()
        exif = Path(shutil.which('exiftool')).resolve()
        shutil.copy2(exif, tools / 'exiftool')
        tool = tools / 'exiftool'
        tool.chmod(0o755)
        tool.write_text('#!/usr/bin/perl\n' + tool.read_text().split('\n', 1)[1])
        shutil.copytree(exif.parent.parent / 'libexec/lib', tools / 'lib')
        (tools / 'exiftool').chmod(0o755)
        licenses = resources / 'Licenses'
        shutil.copytree(ROOT.parent / 'Third-Party-Licenses', licenses)
        shutil.copytree(ROOT / 'vendor/libraw-source', licenses / 'LibRaw-source',
                        ignore=shutil.ignore_patterns('.git', '.jsr-patched'))
        shutil.copy2(ROOT.parent / 'Third-Party-Licenses/LibRaw/libraw-0.22.2-nikon-he.patch', licenses / 'LibRaw-source/Nikon-HE.patch')
        print('Building embedded native Metal bridge', flush=True)
        print(run([sys.executable, ROOT / 'build_metal.py', '--embed-fusion', '--output', vendor / 'metal/jsr_graph.dylib']), flush=True)
    print('Relocating and signing Mach-O dependencies', flush=True)
    dependencies = relocate(resources, [(base, runtime), (site, bundled_site), (ROOT / 'vendor', vendor)])
    native_record = vendor / 'metal/jsr_graph.build.json'
    native = json.loads(native_record.read_text())
    native['library_sha256'] = hashlib.sha256(native_record.with_name('jsr_graph.dylib').read_bytes()).hexdigest()
    native['embedded_fusion_shader'] = True
    native_record.write_text(json.dumps(native, indent=2))
    macos = contents / 'MacOS'
    macos.mkdir(exist_ok=True)
    launcher = macos / 'jsr-cli'
    run(['xcrun', 'clang', '-arch', 'arm64', '-O2', '-mmacosx-version-min=14.0',
         ROOT / 'native/portable_launcher.c', '-o', launcher])
    run(['codesign', '--force', '--sign', '-', launcher])
    finder = macos / 'JSR'
    finder.unlink(missing_ok=True)
    shutil.copy2(launcher, finder)
    if not (resources / 'macos').exists():
        (resources / 'macos').symlink_to('engine', target_is_directory=True)
    (contents / 'Info.plist').write_bytes(plistlib.dumps({
        'CFBundleIdentifier':'com.f1justin.jsrbridge.preview', 'CFBundleName':'JSR Bridge',
        'CFBundleDisplayName':'JSR Bridge', 'CFBundleExecutable':'JSR', 'CFBundlePackageType':'APPL',
        'CFBundleVersion':'1', 'CFBundleShortVersionString':'2.3.9',
        'NSHighResolutionCapable':True,'LSMinimumSystemVersion':'14.0'}))
    wrapper = output / 'jsr'
    wrapper.write_text('''#!/bin/zsh
set -eu
here="$(cd "$(dirname "$0")" && pwd)"
exec "$here/JSR Bridge.app/Contents/MacOS/jsr-cli" "$@"
''')
    wrapper.chmod(0o755)
    (output / '启动 GUI.command').write_text('''#!/bin/zsh
set -eu
here="$(cd "$(dirname "$0")" && pwd)"
exec "$here/jsr" gui
''')
    (output / '启动 GUI.command').chmod(0o755)
    (output / '使用说明.txt').write_text('''Jiangtherapee Bridge 2.3.9 · macOS arm64 portable preview 1

要求：Apple Silicon，macOS 14 或更高版本。已在 M2 Pro / macOS 27.2 验证。
解压并保持整个目录完整，双击 JSR Bridge.app 或 启动 GUI.command。
同包包含 Python、三种模式的模型、LibRaw Nikon HE 解码器和 ExifTool。
无需安装 Python、Homebrew、Xcode；处理过程使用本地文件。

命令行（先在终端进入本目录）：
./jsr --help
./jsr doctor --self-test
./jsr fast --help
./jsr stormer --help
./jsr v98 --help

v9.8 全图示例：
./jsr v98 --raw-frame /路径/01.nef [继续重复 --raw-frame，合计14张] --output-dir /输出/新目录 --cache-mode memmap --prepare-mmap-cache --resource-mode balanced --camera-profile-source libraw --out-dng on --out-tiff on --out-png off

Fast 使用14张；Stormer使用7张；v9.8使用14张。
Fast/Stormer需匹配暗场或手动标定，GUI里的0 DN/20000电子是测试参数。
输出、配准缓存和处理日志保存在所选输出目录。保留足够的磁盘空间。
移动整个 portable 目录后，GUI和CLI仍使用同包依赖。

本包采用本机 ad-hoc 签名，尚未 Apple notarization。系统可能提示来源未验证。
请使用系统设置中的“隐私与安全性 → 仍要打开”批准本包。
第三方许可、LibRaw源码及Nikon HE补丁在应用 Contents/Resources/Licenses。
本包是本地预览产物，公开发布范围由作者确认。
''')
    run(['codesign', '--force', '--sign', '-', app])
    run(['codesign', '--verify', '--deep', '--strict', app])
    (output / 'BUILD.json').write_text(json.dumps({'version':VERSION,'architecture':'arm64','minimum_macos':'14.0',
        'python':sys.version.split()[0],'dependencies':dependencies,'signature':'ad-hoc; not notarized'}, indent=2))
    print(output, flush=True)


if __name__ == '__main__':
    main()
