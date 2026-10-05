"""Extract version-locked Tauri web assets from the official Windows release."""
from pathlib import Path
import hashlib
import struct
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parent
ARCHIVE_HASH = '66367390fd0efdc46002411b9117685716258d3bed0571ac74ecbe83d2c31c06'
REQUIRED = {'index.html', 'style.css', 'jsr.css', 'desktop.js', 'jsr.js', 'assets/author.jpg', 'updates.js', 'timeline.js', 'app.js'}


def extract():
    archive = ROOT / 'vendor/Jiangtherapee-Bridge-2.3.9-Windows-x64.zip'
    if hashlib.sha256(archive.read_bytes()).hexdigest() != ARCHIVE_HASH:
        raise RuntimeError('Official 2.3.9 archive checksum mismatch')
    with zipfile.ZipFile(archive) as package:
        executable = package.read('Jiangtherapee-Bridge-2.3.9-Windows-x64/Jiangtherapee Bridge.exe')
    pe = struct.unpack_from('<I', executable, 0x3c)[0]
    count, optional_size = struct.unpack_from('<H', executable, pe + 6)[0], struct.unpack_from('<H', executable, pe + 20)[0]
    image_base = struct.unpack_from('<Q', executable, pe + 24 + 24)[0]
    sections = []
    for index in range(count):
        offset = pe + 24 + optional_size + index * 40
        virtual_size, address, raw_size, raw_offset = struct.unpack_from('<IIII', executable, offset + 8)
        sections.append((address, max(virtual_size, raw_size), raw_offset))
    def position(pointer):
        rva = pointer - image_base
        for address, size, raw_offset in sections:
            if address <= rva < address + size:
                return rva - address + raw_offset
        raise ValueError('PE pointer outside sections')
    destination = ROOT / 'vendor/original-ui'
    found = set()
    with tempfile.TemporaryDirectory(prefix='jsr-web-assets-') as temporary:
        compressed = Path(temporary) / 'asset.br'
        for entry in range(0x94ddb8 - 18 * 32, 0x94ddb8 + 8 * 32, 32):
            key_ptr, key_len, value_ptr, value_len = struct.unpack_from('<QQQQ', executable, entry)
            if not 1 <= key_len <= 80:
                continue
            try:
                key = executable[position(key_ptr):position(key_ptr) + key_len].decode().lstrip('/')
            except (ValueError, UnicodeDecodeError):
                continue
            if key not in REQUIRED:
                continue
            target = destination / key
            target.parent.mkdir(parents=True, exist_ok=True)
            compressed.write_bytes(executable[position(value_ptr):position(value_ptr) + value_len])
            subprocess.run(['brotli', '-d', '-f', str(compressed), '-o', str(target)], check=True)
            found.add(key)
    if found != REQUIRED:
        raise RuntimeError('Missing author assets: ' + str(REQUIRED - found))
    print('Extracted %d original GUI assets' % len(found))


if __name__ == '__main__':
    extract()
