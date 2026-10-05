"""Prepare author GUI assets and the macOS-specific backend controls."""
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parent


def build(destination):
    destination.mkdir(parents=True, exist_ok=True)
    for source in (ROOT / 'web').iterdir():
        if source.is_file():
            shutil.copy2(source, destination / source.name)
    original = ROOT / 'vendor/original-ui'
    shutil.copytree(original, destination / 'original', dirs_exist_ok=True)
    source = (original / 'jsr.js').read_text()
    edits = {
        "}else{\n  if(!dark||": "}else if(engine!=='v98k14'){\n  if(!dark||",
        "$('#jsr-dark-fields').hidden=!k&&$('#jsr-manual').checked;": "$('#jsr-dark-fields').hidden=engine==='v98k14'||(!k&&$('#jsr-manual').checked);",
        "内置无损压缩线性 DNG（Compression=7），无需 Adobe DNG Converter。": "相机线性 DNG；当前 v9.8 macOS 输出使用无压缩编码。",
        "第24500步最佳权重 · 整图 · 内置无损压缩 DNG": "第24500步最佳权重 · 整图 · MPSGraph / Metal",
        "if(k)setMode('full');": "$('#jsr-tiff').parentNode.lastChild.textContent=engine==='v98k14'?'彩色 TIFF16':'线性 TIFF16';if(k)setMode('full');",
        "已停止，未完成文件保留在 .partial 目录": "已停止，已有输出保留在任务目录",
    }
    for before, after in edits.items():
        if source.count(before) != 1:
            raise RuntimeError('Author UI adaptation anchor changed: ' + before)
        source = source.replace(before, after)
    (destination / 'jsr-mac.js').write_text(source)


if __name__ == '__main__':
    import sys
    build(Path(sys.argv[1]))
