"""JSON line transport between WKWebView and the three local engines."""
from pathlib import Path
from datetime import datetime
import csv
import re
import base64
import io
import json
import math
import os
import signal
import subprocess
import sys
import threading
import uuid
from camera_presets import capture_metadata, resolve_z8
from batch_workflow import scan

ROOT = Path(__file__).resolve().parent
RAW_EXTENSIONS = {'.nef', '.arw', '.cr2', '.cr3', '.dng', '.raf', '.rw2', '.orf', '.pef', '.srw', '.nrw'}


def number(value, name, minimum=0, maximum=1e12):
    result = float(value)
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise ValueError(name + '超出范围')
    return result


class Bridge:
    def __init__(self):
        self.selected = {'paths': []}
        self.process = None
        self.collector = None
        self.engine = None
        self.output = None
        self.log = ''
        self.state = 'idle'
        self.lock = threading.Lock()
        self.selections = {}
        self.preset = None

    def select(self, payload):
        if self.state == 'running':
            raise ValueError('当前计算正在进行')
        paths = [str(Path(p).expanduser().resolve(strict=True)) for p in payload.get('paths', [])]
        if len(paths) > 256 or len(set(paths)) != len(paths):
            raise ValueError('请选择最多256张互不重复的 RAW')
        if any(Path(p).suffix.lower() not in RAW_EXTENSIONS or not Path(p).is_file() for p in paths):
            raise ValueError('输入文件须为 RAW')
        if not paths:
            self.selected = {'paths': []}
            return self.selected
        import rawpy
        from PIL import Image
        metadata = capture_metadata(paths)
        ref = (7 if payload.get('engine') == 'v98k14' else 6) if len(paths) == 14 else len(paths) // 2
        def exposure(row):
            shutter = row.get('ExposureTime', 0)
            aperture = row.get('FNumber', 1)
            return float(shutter or 0) / float(aperture or 1) ** 2
        reference_exposure = exposure(metadata[ref])
        frames = []
        for index, row in enumerate(metadata):
            value = exposure(row)
            frames.append({'name': Path(paths[index]).name, 'iso': row.get('ISO'), 'shutter': row.get('ExposureTime'),
                           'camera': row.get('Model', ''), 'nef_compression': row.get('NEFCompression'), 'ev': math.log2(value / reference_exposure) if value and reference_exposure else 0,
                           'reference': index == ref})
        with rawpy.imread(paths[ref]) as raw:
            height, width = raw.raw_image_visible.shape
            black, white = sum(raw.black_level_per_channel) / 4, raw.white_level
            # Sensor coordinates must agree with the ROI passed to the reconstruction engine.
            try:
                rgb = raw.postprocess(half_size=True, user_flip=0, use_camera_wb=True, output_bps=8)
            except Exception:
                import numpy as np
                grey = np.clip((raw.raw_image_visible[::4, ::4].astype(float) - black) / max(1, white - black), 0, 1)
                rgb = np.repeat((grey ** (1/2.2) * 255).astype(np.uint8)[..., None], 3, axis=2)
        image = Image.fromarray(rgb)
        image.thumbnail((1600, 1200))
        buffer = io.BytesIO()
        image.save(buffer, format='JPEG', quality=88)
        self.selected = {'paths': paths, 'width': width, 'height': height, 'black': black, 'white': white,
                         'preview': 'data:image/jpeg;base64,' + base64.b64encode(buffer.getvalue()).decode(),
                         'frames': frames, 'reference': ref, 'selection_id': uuid.uuid4().hex, 'reference_name': Path(paths[ref]).name, 'warnings': [],
                         'exposure_confirmation_required': any(not f['shutter'] for f in frames),
                         'ptc_auto_available': False, 'ptc_issue': '当前包使用明确填写的满阱或手动标定参数。',
                         'fast_fullwell_resolution': {'matched': False}, 'fast_fullwell_e': 20000}
        if len(self.selections) >= 512:
            raise ValueError('本次批量最多缓存512组，请重新开始批量准备')
        self.selections[self.selected['selection_id']] = self.selected
        return self.selected

    def command(self, p):
        engine = p.get('engine')
        names = {'fastk14': 'run_fast', 'stormer7': 'run_stormer', 'v98k14': 'run_v98'}
        if engine not in names:
            raise ValueError('未知计算模式')
        if p.get('selection_id'):
            if p['selection_id'] not in self.selections:
                raise ValueError('批量选择已过期，请重新准备')
            self.selected = self.selections[p['selection_id']]
        p = dict(p)
        self.preset = resolve_z8(self.selected) if p.get('camera_preset') == 'z8' else None
        if self.preset:
            p.update(dark=self.preset['dark'], fullwell=self.preset['fullwell_e'], manual=False, confirmed=True, ptc='')
        paths = self.selected['paths']
        expected = 7 if engine == 'stormer7' else 14
        if len(paths) != expected:
            raise ValueError('当前模式需要%d张 RAW' % expected)
        if engine != 'stormer7':
            frames = self.selected['frames']
            if any(abs(f['ev']) > math.log2(1.02) for f in frames):
                raise ValueError('十四帧模式需要同曝光连拍')
            if len({f['camera'] for f in frames}) > 1 or len({f['iso'] for f in frames}) > 1:
                raise ValueError('十四帧模式需要相同相机与 ISO')
        if self.selected['exposure_confirmation_required'] and not (p.get('equal_exposure_confirmed') or p.get('exposures')):
            raise ValueError('请确认实际曝光关系')
        destination = Path(p['output']).expanduser().resolve()
        if not destination.is_dir():
            if p.get('batch_audit') and destination.parent.parent.is_dir():
                pass
            else:
                raise ValueError('请选择已存在的输出文件夹')
        prefix = str(p.get('prefix', '')).strip()
        if not prefix or len(prefix) > 80 or any(c in prefix for c in '<>:"/\\|?*') or any(ord(c) < 32 for c in prefix):
            raise ValueError('文件名前缀无效')
        if not any(p.get(k) for k in ('dng', 'tiff', 'preview')):
            raise ValueError('至少选择一种输出格式')
        output = destination / ('JSR_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
        runner = ROOT / (names[engine] + '.py')
        if not runner.exists():
            runner = runner.with_suffix('.pyc')
        command = [sys.executable, '-u', str(runner), '--output-dir', str(output), '--out-prefix', prefix]
        for path in paths:
            command += ['--raw-frame', path]
        for key, flag in [('dng', '--out-dng'), ('tiff', '--out-tiff'), ('preview', '--out-png')]:
            command += [flag, 'on' if p.get(key) else 'off']
        format_ = p.get('format', 'jpeg')
        if format_ not in ('jpeg', 'png'):
            raise ValueError('预览格式无效')
        command += ['--out-format', format_, '--jpeg-quality', str(int(number(p.get('quality', 95), 'JPEG质量', 1, 100)))]
        color = p.get('color', 'auto')
        if color in ('auto', 'embedded-dng', 'libraw'):
            command += ['--camera-profile-source', color]
        else:
            command += ['--camera-profile-source', 'libraw', '--camera-model', str(color)]
        if p.get('memory') is not None:
            command += ['--memory-gb', str(number(p['memory'], 'GPU预算', .1, 128))]
        if engine == 'v98k14':
            command += ['--cache-mode', 'memmap', '--prepare-mmap-cache', '--resource-mode', 'balanced']
            if p.get('dark'):
                command += ['--dark-frame', str(Path(p['dark']).resolve(strict=True))]
        else:
            if p.get('fullwell') is not None:
                command += ['--full-well-electrons' if engine == 'stormer7' else '--fullwell', str(number(p['fullwell'], '满阱', 1))]
            elif engine == 'stormer7' and not p.get('ptc'):
                raise ValueError('请填写满阱容量')
            if p.get('manual'):
                black = number(p['black'], '黑电平', 0, self.selected['white'] - 1)
                noise = number(p['read_noise'], '读噪声')
                if engine == 'stormer7':
                    command += ['--developer-mode', '--black-level-dn', str(black), '--read-noise-dn', str(noise)]
                else:
                    command += ['--black', str(black), '--read-noise', str(noise / (self.selected['white'] - black))]
            else:
                dark = Path(p.get('dark') or '').expanduser().resolve()
                if not dark.is_file() or dark.suffix.lower() not in RAW_EXTENSIONS:
                    raise ValueError('请选择匹配暗场并确认拍摄条件')
                command += ['--dark-frame', str(dark)]
                if engine == 'stormer7':
                    command += ['--confirm-dark-settings']
            if engine == 'fastk14':
                command += ['--host-memory-gb', str(number(p.get('host_memory', 12), '内存预算', 2, 1024)),
                            '--cpu-cores', str(int(number(p.get('cpu_cores', 4), 'CPU核心', 1, os.cpu_count())))]
            else:
                command += ['--reference-index', str(self.selected['reference']), '--backend', 'Metal', '--grid', '256', '--deghost', 'on' if p.get('deghost') else 'off']
                if p.get('ptc'):
                    command += ['--ptc-proxy', str(p['ptc'])]
                if p.get('exposures'):
                    values = p['exposures']
                    if len(values) != 7:
                        raise ValueError('曝光比例需要七个值')
                    command += ['--exposure-ratios', *[str(number(v, '曝光比例', 1e-9)) for v in values]]
                elif p.get('equal_exposure_confirmed'):
                    command += ['--confirm-equal-exposure']
        if p.get('mode') == 'roi':
            if engine != 'stormer7':
                raise ValueError('局部框选使用 Stormer 模式')
            x, y, w, h = [int(number(v, 'ROI坐标')) for v in p['roi']]
            if x % 2 or y % 2 or w % 8 or h % 8 or min(w, h) < 64 or x + w > self.selected['width'] or y + h > self.selected['height']:
                raise ValueError('ROI须在传感器范围内，原点对齐2、尺寸对齐8')
            command += ['--roi', *map(str, (x, y, w, h))]
        return command, output

    def start(self, p):
        if self.state == 'running':
            raise ValueError('当前计算正在进行')
        command, output = self.command(p)
        output.mkdir(parents=True)
        if self.preset:
            (output / 'CAMERA_PRESET.json').write_text(json.dumps(self.preset, ensure_ascii=False, indent=2))
        if p.get('batch_audit'):
            (output / 'BATCH_GROUP.json').write_text(json.dumps(p['batch_audit'], ensure_ascii=False, indent=2))
        environment = os.environ.copy()
        environment['JSR_METAL_NETWORKS'] = 'mpsgraph'
        self.process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
                                        start_new_session=True, env=environment)
        with self.lock:
            self.state, self.log, self.output = 'running', '', output
            self.engine = p['engine']
        self.collector = threading.Thread(target=self.collect, daemon=True)
        self.collector.start()
        return {'state': 'running', 'output': str(output)}

    def collect(self):
        process = self.process
        with (self.output / 'processing.log').open('w') as saved:
            for line in process.stdout:
                saved.write(line)
                saved.flush()
                with self.lock:
                    self.log = (self.log + line)[-2_000_000:]
                    if self.engine == 'v98k14' and line.startswith('SRHQ_ETA_PROGRESS|'):
                        parts = line.strip().split('|')
                        if len(parts) >= 4:
                            try:
                                stages = {'decode': (0, 5), 'align': (5, 15), 'rms': (20, 2), 'merge': (22, 30),
                                          'lca': (52, 3), 'refine': (55, 35), 'highlight': (90, 2), 'render': (92, 2),
                                          'tiff': (94, 2), 'dng': (96, 2), 'compression': (98, 1), 'manifest': (99, 1)}
                                start, span = stages.get(parts[1], (0, 0))
                                progress = start + span * min(1, float(parts[2]) / max(1, float(parts[3])))
                                self.log += 'SRHQ_V12_PROGRESS|%.1f|%s\n' % (progress, parts[1])
                            except ValueError:
                                pass
        code = process.wait()
        with self.lock:
            if self.state == 'running':
                self.state = 'complete' if code == 0 else 'failed'
                self.log += '\n进程退出码：%d\n' % code

    def cancel(self):
        process = self.process
        if process and process.poll() is None:
            with self.lock:
                self.state = 'cancelled'
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
        if self.collector and self.collector.is_alive():
            self.collector.join(timeout=10)
        return {'state': self.state}

    def request(self, route, payload):
        if route == 'jsr/camera-preset':
            selected = self.selections.get(payload.get('selection_id'), self.selected)
            return resolve_z8(selected)
        if route == 'jsr/batch-scan':
            return scan(payload['folder'], payload.get('recursive', True),
                        7 if payload.get('engine') == 'stormer7' else 14, RAW_EXTENSIONS)
        if route == 'jsr/batch-clear-selections':
            if self.state == 'running':
                raise ValueError('当前计算正在进行')
            self.selections.clear()
            return {}
        if route == 'jsr/batch-validate':
            self.command(payload)
            return {'valid': True}
        if route == 'jsr/batch-thumbs':
            from PIL import Image
            import rawpy
            photos = []
            for path in payload.get('paths', [])[:14]:
                try:
                    with rawpy.imread(path) as raw:
                        rgb = raw.postprocess(half_size=True, user_flip=0, use_camera_wb=True, output_bps=8)
                    image = Image.fromarray(rgb); image.thumbnail((240, 180))
                    buffer = io.BytesIO(); image.save(buffer, format='JPEG', quality=75)
                    photos.append({'path': path, 'preview': 'data:image/jpeg;base64,' + base64.b64encode(buffer.getvalue()).decode()})
                except Exception as error:
                    photos.append({'path': path, 'preview_issue': str(error)})
            return {'photos': photos}
        if route == 'jsr/batch-report':
            report = payload['report']
            destination = Path(report['output']).expanduser().resolve()
            if not destination.name.startswith('batch-') or not destination.parent.is_dir():
                raise ValueError('批量报告路径无效')
            destination.mkdir(exist_ok=True)
            target = destination / 'BATCH.json'
            temporary = target.with_suffix('.tmp')
            temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2))
            temporary.replace(target)
            return {'path': str(target)}
        if route == 'jsr/options':
            index = ROOT / 'vendor/stormer/product_v152/ptc_index.csv'
            rows = []
            with index.open() as stream:
                for row in csv.DictReader(stream):
                    alpha = float(row.get('alpha') or 0)
                    if alpha > 0:
                        rows.append({'key': row['sensor_id'] + ':' + row['iso_nominal'],
                                     'label': '%s %s · ISO %s · %.0f e⁻' % (row['brand'], row['model'].strip(), row['iso_nominal'], 1 / alpha)})
            matrix = ROOT / 'vendor/stormer/product_v152/legacy/cameraMatrices.data'
            cameras = re.findall(r'^\s*"([^"]+)"\s*:', matrix.read_text(), re.MULTILINE)
            return {'version': '15.3.5 · Metal', 'ptc': rows, 'cameras': sorted(set(cameras))}
        if route == 'jsr/select':
            return self.select(payload)
        if route == 'jsr/start':
            return self.start(payload)
        if route == 'jsr/status':
            with self.lock:
                return {'state': self.state, 'log': self.log, 'output': str(self.output or '')}
        if route == 'jsr/cancel':
            return self.cancel()
        raise ValueError('未知请求：' + route)


def main():
    bridge = Bridge()
    try:
        for line in sys.stdin:
            try:
                message = json.loads(line)
                result = bridge.request(message['route'], message.get('payload', {}))
                reply = {'id': message['id'], 'result': result}
            except Exception as error:
                reply = {'id': message.get('id') if isinstance(locals().get('message'), dict) else None, 'error': str(error)}
            print(json.dumps(reply, ensure_ascii=False), flush=True)
    finally:
        bridge.cancel()


if __name__ == '__main__':
    main()
