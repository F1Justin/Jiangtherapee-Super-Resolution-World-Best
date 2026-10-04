"""Discover the separately contributed portable reconstruction helpers."""
from pathlib import Path
import importlib
import sys


def generic_optimizations():
    core = str(Path(__file__).resolve().parents[1] / 'Core-Only-Source-Code')
    if core not in sys.path:
        sys.path.append(core)
    try:
        return importlib.import_module('reconstruction_optimizations')
    except ModuleNotFoundError as error:
        if error.name != 'reconstruction_optimizations':
            raise
        return None
