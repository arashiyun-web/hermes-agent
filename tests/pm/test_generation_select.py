"""Pin and reselect complete dependency generations without touching their trees."""

import hashlib
import json
from pathlib import Path

import pytest

OLD = "82cffae052ae4bfcaaf046f437117a31"
NEW = "a5266fa2427948f0858e22af807f9102"


def _marker(venv: Path, text: str) -> None:
    site = venv / "lib" / "python3.12" / "site-packages"
    site.mkdir(parents=True)
    (site / "marker.txt").write_text(text, encoding="utf-8")


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def install(tmp_path, monkeypatch):
    from pm.environments import install_state_dir, runtime_facts_path

    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    state = install_state_dir(repo)
    generations = {}
    for name, marker in ((OLD, "old-tree"), (NEW, "new-tree")):
        venv = state / "environments" / name / "venv"
        venv.mkdir(parents=True)
        (venv / "pyvenv.cfg").write_text("home = /usr\nversion = 3.12.3\n", encoding="utf-8")
        _marker(venv, marker)
        generations[name] = venv.resolve()
    facts = runtime_facts_path(repo)
    facts.parent.mkdir(parents=True, exist_ok=True)
    facts.write_text(json.dumps({
        "schema": 1,
        "packages": {
            "python": {"entry": "python-kept", "version": "3.12.3"},
            "venv": {
                "stamp": "original-stamp",
                "extras": ["web"],
                "environment": str(generations[OLD]),
            },
        },
    }), encoding="utf-8")
    monkeypatch.setattr(
        "pm.packages.Venv.expected_stamp",
        lambda self, extras, plugin_dirs=None: "now:" + ",".join(extras),
    )
    return repo, facts, generations


def test_pin_records_the_generation_and_leaves_facts_bytes_unchanged(install):
    from pm.generation_select import pin_current_generation

    repo, facts, generations = install
    before = facts.read_bytes()
    assert pin_current_generation(repo) == OLD
    assert facts.read_bytes() == before
    pin = json.loads((generations[OLD].parent / "selection.json").read_text(encoding="utf-8"))
    assert pin["generation"] == OLD
    assert pin["fact"]["extras"] == ["web"]
    assert pin["fact"]["environment"] == str(generations[OLD])


def test_select_restores_the_pinned_generation_without_changing_its_tree(install):
    from pm.generation_select import pin_current_generation, select_generation
    from pm.lock import Facts

    repo, facts, generations = install
    old_digest = _digest(generations[OLD] / "lib" / "python3.12" / "site-packages" / "marker.txt")
    pin_current_generation(repo)
    Facts(facts, strict=True).record_state(
        "venv", "now:web,mcp", ["mcp", "web"], environment=generations[NEW],
    )
    assert select_generation(repo, OLD) == OLD
    selected = Facts(facts, strict=True).get("venv")
    assert selected["environment"] == str(generations[OLD])
    assert selected["extras"] == ["web"]
    assert selected["stamp"] == "now:web"
    assert Facts(facts, strict=True).get("python")["entry"] == "python-kept"
    assert _digest(generations[OLD] / "lib" / "python3.12" / "site-packages" / "marker.txt") == old_digest
    assert (generations[NEW] / "pyvenv.cfg").is_file()


def test_select_refuses_a_generation_outside_this_install(install, tmp_path):
    from pm.generation_select import GenerationSelectError, select_generation

    repo, facts, generations = install
    before = facts.read_bytes()
    foreign = tmp_path / "val" / "pm-envs" / "gen-a5266fa2427948f0858e22af807f9102" / "venv"
    foreign.mkdir(parents=True)
    (foreign / "pyvenv.cfg").write_text("version = 3.14.7\n", encoding="utf-8")
    record = {
        "schema": 1,
        "generation": OLD,
        "fact": {
            "stamp": "original-stamp",
            "extras": ["web"],
            "environment": str(foreign.resolve()),
        },
    }
    (generations[OLD].parent / "selection.json").write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(GenerationSelectError, match="not this generation"):
        select_generation(repo, OLD)
    assert facts.read_bytes() == before


def test_select_refuses_an_incomplete_or_unpinned_generation(install):
    from pm.generation_select import GenerationSelectError, select_generation

    repo, _, generations = install
    with pytest.raises(GenerationSelectError, match="no pin"):
        select_generation(repo, NEW)
    (generations[NEW] / "pyvenv.cfg").unlink()
    (generations[NEW].parent / "selection.json").write_text(json.dumps({
        "schema": 1,
        "generation": NEW,
        "fact": {"stamp": "s", "extras": [], "environment": str(generations[NEW])},
    }), encoding="utf-8")
    with pytest.raises(GenerationSelectError, match="no complete venv"):
        select_generation(repo, NEW)


def test_cli_select_rejects_an_id_that_is_not_a_generation_directory():
    from pm.cli import main

    assert main(["generation", "select", "not-a-generation-id"]) == 1


def test_mcp_extra_is_unioned_onto_the_recorded_graph(tmp_path):
    from pm.install import _target_selection

    class Package:
        def project_root(self):
            return tmp_path

        def expected_stamp(self, extras, **kwargs):
            return ",".join(extras)

    enabled, _stamp, _inputs = _target_selection(
        Package(),
        {"extras": ["voice", "web"], "stamp": "old"},
        extras=["mcp"],
        inputs={},
        repair=False,
        shipped=[],
        frozen=None,
    )
    assert enabled == ["mcp", "voice", "web"]
