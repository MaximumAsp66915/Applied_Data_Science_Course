"""Root test configuration for the engine and its learning layer.

Both suites import their modules by bare name (`from artifacts import ...`,
`from bandit import ...`), which needs two directories on `sys.path`. That is
normally a `pythonpath` entry in `pytest.ini` -- but this folder and the
`algorithm improvement/` package both contain spaces, and pytest's ini list
options are split on whitespace, so a path with a space in it cannot be
expressed there. Doing it here instead is the reliable way.

With no `testpaths` set, pytest discovers both `tests/` and
`algorithm improvement/tests/` from the root, so `python -m pytest` runs
everything.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
for path in (ROOT, ROOT / "algorithm improvement"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

# Share the engine's dataset fixtures (`params`, `config`, `engine`) with both
# test directories. Re-exporting them here rather than importing them inside
# `algorithm improvement/tests/conftest.py` is the structurally correct place:
# a fixture defined in the root conftest is visible to every test below it, so
# the learning layer is exercised against the same miniature catalogue the
# ranking code is, with no cross-directory imports.
#
# `__all__` marks them as a deliberate re-export rather than dead imports.
from tests.conftest import config, engine, params  # noqa: E402

__all__ = ["config", "engine", "params"]
