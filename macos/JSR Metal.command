#!/bin/zsh
set -e
task_dir="$(cd "$(dirname "$0")" && pwd)"
exec "$task_dir/.venv/bin/python" "$task_dir/gui.py"
