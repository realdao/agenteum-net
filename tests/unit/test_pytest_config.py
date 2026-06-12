from __future__ import annotations

import tomllib
from pathlib import Path


def test_e2e_tests_are_excluded_by_default() -> None:
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    config = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    pytest_config = config["tool"]["pytest"]["ini_options"]

    assert pytest_config["addopts"] == "-m 'not e2e'"
    assert any(marker.startswith("e2e:") for marker in pytest_config["markers"])
