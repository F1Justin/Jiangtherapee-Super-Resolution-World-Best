"""Build a local app launcher for the prepared Metal environment."""

from pathlib import Path
import plistlib


root = Path(__file__).resolve().parent
contents = root / "JSR Metal.app" / "Contents"
binary = contents / "MacOS" / "JSR"
binary.parent.mkdir(parents=True, exist_ok=True)
(contents / "Info.plist").write_bytes(plistlib.dumps({
    "CFBundleIdentifier": "local.jsr.metal",
    "CFBundleName": "JSR Metal",
    "CFBundleDisplayName": "JSR Metal",
    "CFBundleExecutable": "JSR",
    "CFBundlePackageType": "APPL",
    "CFBundleVersion": "2.3.9",
    "CFBundleShortVersionString": "2.3.9",
    "NSHighResolutionCapable": True,
    "LSMinimumSystemVersion": "13.0",
}))
binary.write_text('''#!/bin/zsh
set -e
task_dir="$(cd "$(dirname "$0")/../../.." && pwd)"
mkdir -p "$task_dir/validation"
exec "$task_dir/.venv/bin/python" "$task_dir/gui.py" > "$task_dir/validation/gui.log" 2>&1
''')
binary.chmod(0o755)
print(contents.parent)
