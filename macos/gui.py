"""Native file selection and progress for the three Bridge Metal backends."""

from __future__ import annotations

from datetime import datetime
import math
import os
from pathlib import Path
import queue
import signal
import subprocess
import sys
import threading

for variable, directory in (("TCL_LIBRARY", "tcl8.6"), ("TK_LIBRARY", "tk8.6")):
    library = Path(sys.base_prefix) / "lib" / directory
    if library.is_dir():
        os.environ.setdefault(variable, str(library))

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import rawpy


ROOT = Path(__file__).resolve().parent


class Application:
    def __init__(self, window: tk.Tk):
        self.window = window
        self.files: list[str] = []
        self.process = None
        self.busy = False
        self.cancel_requested = threading.Event()
        self.events = queue.Queue()
        window.title("JSR · Metal")
        window.geometry("840x700")
        outer = ttk.Frame(window, padding=20)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="Jiangtherapee · Metal", font=("Helvetica", 22, "bold")).pack(anchor="w")
        ttk.Label(outer, text="Apple Silicon · RAW 连拍 → 2 倍边长 DNG / TIFF").pack(anchor="w", pady=(6, 12))
        self.mode = tk.StringVar(value="Fast K14")
        selector = ttk.Combobox(outer, textvariable=self.mode, values=["Fast K14", "Stormer · 7 帧", "v9.8 K14"], state="readonly")
        selector.pack(anchor="w", pady=(0, 12))
        self.network_backend = tk.StringVar(value='Apple 优化 · FP32')
        backend_row = ttk.Frame(outer)
        backend_row.pack(anchor='w', pady=(0, 12))
        ttk.Label(backend_row, text='v9.8 计算方式').pack(side='left', padx=(0, 12))
        ttk.Combobox(backend_row, textvariable=self.network_backend,
                     values=['Apple 优化 · FP32', '原版 WGPU · FP32'], state='readonly', width=24).pack(side='left')
        row = ttk.Frame(outer)
        row.pack(fill="x")
        ttk.Button(row, text="选择 RAW 连拍", command=self.select_raws).pack(side="left")
        self.count = tk.StringVar(value="尚未选择照片")
        ttk.Label(row, textvariable=self.count).pack(side="left", padx=12)
        self.destination = tk.StringVar(value=str(Path.home() / "Pictures" / "JSR"))
        self.dark = tk.StringVar()
        self.black = tk.StringVar()
        self.noise = tk.StringVar(value="0")
        self.fullwell = tk.StringVar(value="20000")
        form = ttk.Frame(outer)
        form.pack(fill="x", pady=16)
        form.columnconfigure(1, weight=1)
        for n, (label, variable, action) in enumerate([
            ("输出目录", self.destination, self.select_output),
            ("匹配暗场 RAW", self.dark, self.select_dark),
        ]):
            ttk.Label(form, text=label).grid(row=n, column=0, sticky="w", pady=5)
            ttk.Entry(form, textvariable=variable).grid(row=n, column=1, sticky="ew", padx=12)
            ttk.Button(form, text="选择", command=action).grid(row=n, column=2)
        calibration = ttk.Frame(outer)
        calibration.pack(fill="x")
        ttk.Label(calibration, text="手动标定：黑电平 DN").pack(side="left")
        ttk.Entry(calibration, textvariable=self.black, width=10).pack(side="left", padx=8)
        ttk.Label(calibration, text="读噪声 DN").pack(side="left", padx=(12, 0))
        ttk.Entry(calibration, textvariable=self.noise, width=12).pack(side="left", padx=8)
        ttk.Label(calibration, text="满阱电子数").pack(side="left", padx=(12, 0))
        ttk.Entry(calibration, textvariable=self.fullwell, width=10).pack(side="left", padx=8)
        ttk.Label(outer, text="Fast / Stormer：匹配暗场或手动标定；0 DN / 20000 e⁻ 是测试参数，可填写实测值。\nv9.8 沿用原版标定流程。Stormer 全图耗时较长。").pack(anchor="w", pady=(8, 14))
        buttons = ttk.Frame(outer)
        buttons.pack(fill="x")
        self.start_button = ttk.Button(buttons, text="开始超分", command=self.start)
        self.start_button.pack(side="left")
        self.cancel_button = ttk.Button(buttons, text="停止", command=self.cancel, state="disabled")
        self.cancel_button.pack(side="left", padx=10)
        self.status = tk.StringVar(value="就绪 · 默认 GPU 预算 4 GB / 内存预算 12 GB")
        ttk.Label(buttons, textvariable=self.status).pack(side="left", padx=6)
        self.progress = ttk.Progressbar(outer, maximum=100)
        self.progress.pack(fill="x", pady=12)
        self.log = tk.Text(outer, height=12, wrap="word", state="disabled", font=("Menlo", 11))
        self.log.pack(fill="both", expand=True)
        window.protocol("WM_DELETE_WINDOW", self.close)
        window.after(100, self.poll)

    def select_raws(self):
        paths = filedialog.askopenfilenames(title="选择同一组 RAW 连拍：Stormer 7 张，K14 14 张")
        if not paths:
            return
        self.files = sorted(paths)
        self.count.set(f"已选择 {len(self.files)} 张")
        try:
            with rawpy.imread(self.files[min(6, len(self.files) - 1)]) as raw:
                self.black.set(f"{sum(raw.black_level_per_channel) / 4:g}")
        except Exception as error:
            messagebox.showerror("RAW 解码失败", str(error))

    def select_output(self):
        path = filedialog.askdirectory(title="选择输出目录")
        if path:
            self.destination.set(path)

    def select_dark(self):
        path = filedialog.askopenfilename(title="选择匹配 ISO 的暗场 RAW")
        if path:
            self.dark.set(path)

    def start(self):
        mode = self.mode.get()
        required = 7 if mode.startswith("Stormer") else 14
        if len(self.files) != required:
            messagebox.showerror("输入张数", f"{mode} 使用 {required} 张同组 RAW 连拍。")
            return
        if not self.destination.get().strip():
            messagebox.showerror("输出目录", "请选择输出目录。")
            return
        output = Path(self.destination.get()).expanduser() / datetime.now().strftime("JSR_%Y%m%d_%H%M%S")
        runner = "run_stormer.py" if required == 7 else ("run_v98.py" if mode == "v9.8 K14" else "run_fast.py")
        command = [sys.executable, str(ROOT / runner), "--output-dir", str(output), "--out-tiff", "on"]
        if required == 7:
            command += ["--backend", "Metal", "--grid", "256", "--memory-gb", "4", "--confirm-equal-exposure"]
        elif mode == "v9.8 K14":
            command += ["--cache-mode", "memmap", "--prepare-mmap-cache", "--resource-mode", "balanced", "--camera-profile-source", "libraw", "--out-dng", "on", "--out-png", "off"]
        for path in self.files:
            command += ["--raw-frame", path]
        if mode != "v9.8 K14":
            try:
                fullwell = float(self.fullwell.get())
                if not math.isfinite(fullwell) or fullwell <= 0:
                    raise ValueError
            except ValueError:
                messagebox.showerror("标定参数", "满阱电子数使用正数。")
                return
            command += ["--full-well-electrons" if required == 7 else "--fullwell", str(fullwell)]
        if self.dark.get().strip():
            command += ["--dark-frame", self.dark.get().strip()]
            if required == 7:
                command += ["--confirm-dark-settings"]
        elif mode != "v9.8 K14":
            try:
                black, noise, fullwell = float(self.black.get()), float(self.noise.get()), float(self.fullwell.get())
                if not all(map(math.isfinite, [black, noise, fullwell])) or noise < 0 or fullwell <= 0:
                    raise ValueError("读噪声使用非负数值")
            except ValueError:
                messagebox.showerror("标定参数", "请选择匹配暗场，或填写黑电平、读噪声 DN 与满阱电子数。")
                return
            if required == 7:
                command += ["--developer-mode", "--black-level-dn", str(black), "--read-noise-dn", str(noise)]
            else:
                with rawpy.imread(self.files[6]) as raw:
                    normalized = noise / (raw.white_level - black)
                command += ["--black", str(black), "--read-noise", str(normalized)]
        self.start_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self.progress["value"] = 0
        self.status.set("处理中")
        self.cancel_requested.clear()
        self.busy = True
        environment = os.environ.copy()
        environment['JSR_METAL_NETWORKS'] = 'mpsgraph' if self.network_backend.get().startswith('Apple') else 'wgpu'

        def worker():
            try:
                output.mkdir(parents=True, exist_ok=True)
                self.process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, start_new_session=True, env=environment)
                if self.cancel_requested.is_set():
                    os.killpg(self.process.pid, signal.SIGTERM)
                with (output / "processing.log").open("w", encoding="utf-8") as saved:
                    for line in self.process.stdout:
                        saved.write(line)
                        saved.flush()
                        self.events.put(("line", line))
                code = self.process.wait()
                self.events.put(("done", (code, output)))
            except Exception as error:
                self.events.put(("error", str(error)))

        threading.Thread(target=worker, daemon=True).start()

    def poll(self):
        while not self.events.empty():
            kind, value = self.events.get_nowait()
            if kind == "line":
                self.log.configure(state="normal")
                self.log.insert("end", value)
                self.log.see("end")
                self.log.configure(state="disabled")
                if value.startswith("SRHQ_V12_PROGRESS|"):
                    _, percent, text = value.strip().split("|", 2)
                    self.progress["value"] = int(percent)
                    self.status.set(text)
                elif value.startswith("SRHQ_ETA_PROGRESS|"):
                    _, stage, completed, total = value.strip().split("|", 3)
                    stages = {
                        "decode": (0, 5, "解码"), "align": (5, 15, "对齐"),
                        "rms": (20, 2, "帧检查"), "merge": (22, 30, "融合"),
                        "lca": (52, 3, "色差校正"), "refine": (55, 35, "精修"),
                        "highlight": (90, 2, "高光处理"), "render": (92, 2, "渲染"),
                        "tiff": (94, 2, "TIFF 导出"), "dng": (96, 2, "DNG 导出"),
                        "compression": (98, 1, "压缩"), "manifest": (99, 1, "保存报告"),
                    }
                    if stage in stages:
                        base, span, label = stages[stage]
                        fraction = min(1, int(completed) / max(1, int(total)))
                        self.progress["value"] = base + span * fraction
                        self.status.set(f"{label} · {completed}/{total}")
            else:
                self.process = None
                self.busy = False
                self.start_button.configure(state="normal")
                self.cancel_button.configure(state="disabled")
                if kind == "done" and value[0] == 0:
                    self.status.set("完成 · DNG 与 TIFF 已保存")
                    subprocess.Popen(["open", str(value[1])])
                else:
                    self.status.set("处理已结束 · 查看日志")
                    if kind == "error":
                        messagebox.showerror("启动失败", value)
        self.window.after(100, self.poll)

    def cancel(self):
        self.cancel_requested.set()
        if self.process and self.process.poll() is None:
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            self.status.set("正在停止")

    def close(self):
        if self.busy:
            if not messagebox.askyesno("退出", "退出会停止当前处理。确定退出？"):
                return
            self.cancel()
        self.window.destroy()


if __name__ == "__main__":
    window = tk.Tk()
    Application(window)
    window.mainloop()
