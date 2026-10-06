"""Importing this re-runs the script under the project venv (it holds Pillow), so shebangs can stay portable."""
import os, sys

_D = os.path.dirname(os.path.realpath(__file__))
_PY = os.path.join(_D, ".venv", "bin", "python3")
if os.access(_PY, os.X_OK) and os.path.realpath(sys.prefix) != os.path.join(os.path.realpath(_D), ".venv") and not os.environ.get("CLAUDE_TELEMETRY_VENV"):
    os.environ["CLAUDE_TELEMETRY_VENV"] = "1"  # loop guard: re-exec at most once
    os.execv(_PY, [_PY] + sys.argv)
