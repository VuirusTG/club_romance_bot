import compileall
from pathlib import Path


def test_project_compiles() -> None:
    assert compileall.compile_dir(Path("bot"), quiet=1)

