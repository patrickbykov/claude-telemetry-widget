"""Importing this re-runs the script under the project venv (it holds Pillow), so shebangs can stay portable."""
import os, sys

_D = os.path.dirname(os.path.realpath(__file__))
_PY = os.path.join(_D, ".venv", "bin", "python3")
if os.path.exists(_PY) and os.path.realpath(sys.prefix) != os.path.join(os.path.realpath(_D), ".venv"):
    os.execv(_PY, [_PY] + sys.argv)
