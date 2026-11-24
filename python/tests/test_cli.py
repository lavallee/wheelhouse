"""`wheelhouse new` writes nothing that names the machine it ran on."""
from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from wheelhouse import cli

PACKAGE = Path(cli.__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def checkout(tmp_path, monkeypatch):
    """A stand-in checkout beside the new admins, so the tests do not depend on
    where this repository or the temporary directory happen to live."""
    root = tmp_path / "wheelhouse"
    (root / "python").mkdir(parents=True)
    (root / "python" / "pyproject.toml").write_text("[project]\nname = 'wheelhouse'\n")
    monkeypatch.setattr(cli, "ROOT", root)
    return root / "python"


def new(tmp_path, *extra):
    dest = tmp_path / "admins" / "intake"
    assert cli.main(["new", "intake", "--name", "Intake", "--dir", str(dest), *extra]) == 0
    return dest


def generated_text(dest):
    for path in dest.rglob("*"):
        if path.is_file() and "node_modules" not in path.parts:
            yield path, path.read_text(errors="ignore")


def test_default_source_is_the_public_repository_at_this_version(tmp_path):
    from wheelhouse import __version__
    dest = new(tmp_path)
    source = tomllib.loads((dest / "pyproject.toml").read_text())["tool"]["uv"]["sources"]["wheelhouse"]
    assert source == {"git": cli.PUBLIC_GIT, "subdirectory": "python", "rev": f"v{__version__}"}
    for path, text in generated_text(dest):
        assert str(tmp_path) not in text, path
        assert str(PACKAGE) not in text, path


def test_a_local_checkout_is_written_relative_and_resolves(tmp_path, checkout):
    dest = new(tmp_path, "--wheelhouse", str(checkout))
    source = tomllib.loads((dest / "pyproject.toml").read_text())["tool"]["uv"]["sources"]["wheelhouse"]
    assert source["path"] == "../../wheelhouse/python"
    assert (dest / source["path"]).resolve() == checkout


def test_git_source(tmp_path):
    dest = new(tmp_path, "--wheelhouse", "https://git.example/wheelhouse.git", "--rev", "v0.2.0")
    source = tomllib.loads((dest / "pyproject.toml").read_text())["tool"]["uv"]["sources"]["wheelhouse"]
    assert source == {"git": "https://git.example/wheelhouse.git", "subdirectory": "python", "rev": "v0.2.0"}


def test_explicit_path_is_written_relative(tmp_path, checkout):
    dest = new(tmp_path, "--wheelhouse", str(checkout))
    source = tomllib.loads((dest / "pyproject.toml").read_text())["tool"]["uv"]["sources"]["wheelhouse"]
    assert not Path(source["path"]).is_absolute()


def test_a_path_that_is_not_the_package_is_refused(tmp_path):
    with pytest.raises(SystemExit):
        new(tmp_path, "--wheelhouse", str(tmp_path))
    with pytest.raises(SystemExit):
        new(tmp_path, "--wheelhouse", str(tmp_path / "wheelhouse" / "python"), "--rev", "v1")


def test_names_are_swapped(tmp_path):
    dest = new(tmp_path)
    assert 'APP_ID = "intake"' in (dest / "backend" / "app.py").read_text()
    assert "INTAKE_ADMIN_MODE" in (dest / "dev.sh").read_text()
    assert '"name": "intake-admin-ui"' in (dest / "ui" / "package.json").read_text()


def test_a_path_that_only_meets_at_the_root_is_refused():
    with pytest.raises(SystemExit, match="share no directory"):
        cli._source(Path("/srv/admins/intake"), str(PACKAGE), None)
    assert "git" in cli._source(Path("/srv/admins/intake"), "https://git.example/w.git", None)
