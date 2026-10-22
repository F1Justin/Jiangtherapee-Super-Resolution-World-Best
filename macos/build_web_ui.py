"""Prepare the verified standalone JSR UI with macOS output descriptions."""
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parent


def build(destination):
    destination.mkdir(parents=True, exist_ok=True)
    for source in (ROOT / 'web').iterdir():
        if source.is_file():
            shutil.copy2(source, destination / source.name)
    original = ROOT / 'vendor/original-ui'
    if (destination / 'original').exists():
        shutil.rmtree(destination / 'original')
    shutil.copytree(original, destination / 'original')
    source = (original / 'jsr.js').read_text()
    edits = {
        'DNG 直接保存到此目录；日志集中存入 _logs，重名不会覆盖。':
            '每次合成保存到独立任务目录，保留 processing.log 与诊断；重名不会覆盖。',
        '已停止，未完成文件保留在 .partial 目录': '已停止，已有输出保留在任务目录',
    }
    for before, after in edits.items():
        expected = 2 if before.startswith('已停止') else 1
        if source.count(before) != expected:
            raise RuntimeError('Author UI adaptation anchor changed: ' + before)
        source = source.replace(before, after)
    (destination / 'jsr-mac.js').write_text(source)


if __name__ == '__main__':
    import sys
    build(Path(sys.argv[1]))
