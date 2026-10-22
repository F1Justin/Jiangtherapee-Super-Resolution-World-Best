"""Extract version-verified Tauri assets by their PE pointer table."""
from pathlib import Path
import struct
import subprocess
import tempfile
from release import ROOT, PREFIX, UI_EXECUTABLE, verified_archive

REQUIRED = {'index.html', 'style.css', 'jsr.css', 'desktop.js', 'jsr.js',
            'assets/author.jpg', 'standalone.css', 'standalone.js'}


def extract():
    with verified_archive() as package:
        executable = package.read(PREFIX + UI_EXECUTABLE)
    pe = struct.unpack_from('<I', executable, 0x3c)[0]
    count = struct.unpack_from('<H', executable, pe + 6)[0]
    optional_size = struct.unpack_from('<H', executable, pe + 20)[0]
    image_base = struct.unpack_from('<Q', executable, pe + 48)[0]
    sections = []
    for index in range(count):
        offset = pe + 24 + optional_size + index * 40
        virtual_size, address, raw_size, raw_offset = struct.unpack_from('<IIII', executable, offset + 8)
        sections.append((address, max(virtual_size, raw_size), raw_offset, raw_size))
    def position(pointer, length):
        rva = pointer - image_base
        for address, size, raw_offset, raw_size in sections:
            relative = rva - address
            if 0 <= relative and relative + length <= raw_size:
                return relative + raw_offset
        raise ValueError('PE pointer outside file-backed sections')
    destination = ROOT / 'vendor/original-ui'
    if destination.exists():
        import shutil
        shutil.rmtree(destination)
    found = set()
    with tempfile.TemporaryDirectory(prefix='jsr-web-assets-') as temporary:
        compressed = Path(temporary) / 'asset.br'
        for _, _, raw_offset, raw_size in sections:
            for entry in range(raw_offset, min(raw_offset + raw_size, len(executable)) - 31, 8):
                key_ptr, key_len, value_ptr, value_len = struct.unpack_from('<QQQQ', executable, entry)
                if not 1 <= key_len <= 120 or not 1 <= value_len <= 5_000_000:
                    continue
                try:
                    start = position(key_ptr, key_len)
                    key = executable[start:start + key_len].decode().lstrip('/')
                    if key not in REQUIRED or key in found:
                        continue
                    start = position(value_ptr, value_len)
                except (ValueError, UnicodeDecodeError):
                    continue
                target = destination / key
                target.parent.mkdir(parents=True, exist_ok=True)
                compressed.write_bytes(executable[start:start + value_len])
                subprocess.run(['brotli', '-d', '-f', str(compressed), '-o', str(target)], check=True)
                found.add(key)
    if found != REQUIRED:
        raise RuntimeError('Missing author assets: ' + str(REQUIRED - found))
    print('Extracted %d original GUI assets' % len(found))


if __name__ == '__main__':
    extract()
