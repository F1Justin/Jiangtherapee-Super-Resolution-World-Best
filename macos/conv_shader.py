"""Load the convolution module shipped as Python 3.10 bytecode."""

import marshal
from pathlib import Path

exec(marshal.loads(Path(__file__).with_suffix(".pyc").read_bytes()[16:]))
