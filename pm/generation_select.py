"""Pin and reselect an existing dependency generation.

Publish (``sync_venv`` / ``hermes pm install --extra``) records a new
environment and leaves the previous directory on disk. Nothing in that
path points facts back at a directory that already exists. ``pm repair``
builds another fresh environment from the recorded graph; it is not a
rollback.

``pin`` writes the current venv fact beside that generation and does not
open facts for writing. ``select`` later copies that record back through
``Facts``, after checking the venv is the generation's own complete tree.
The stamp is recomputed for the pinned extras on the current tree so the
next launch does not treat the selection as stale and publish again.
No generation directory is deleted and no package installer runs.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

_GENERATION_ID = re.compile(r"^[0-9a-f]{32}$")


class GenerationSelectError(ValueError):
    """The requested generation cannot be pinned or selected."""


def _state(project: Path):
    from pm.environments import install_state_dir

    return install_state_dir(Path(project))


def _require_id(generation_id: str) -> str:
    if not isinstance(generation_id, str) or _GENERATION_ID.fullmatch(generation_id) is None:
        raise GenerationSelectError("generation id must be the 32-character directory name")
    return generation_id


def _generation_dir(project: Path, generation_id: str) -> Path:
    directory = _state(project) / "environments" / _require_id(generation_id)
    if not directory.is_dir() or directory.is_symlink():
        raise GenerationSelectError(f"generation {generation_id} is not in this install")
    return directory


def _complete_venv(generation_dir: Path) -> Path:
    venv = generation_dir / "venv"
    if venv.is_symlink() or not (venv / "pyvenv.cfg").is_file():
        raise GenerationSelectError("generation has no complete venv")
    resolved = venv.resolve()
    if resolved.parent != generation_dir.resolve():
        raise GenerationSelectError("generation venv escapes its directory")
    return resolved


def _fact_environment(fact: dict, generation_dir: Path) -> Path:
    raw = fact.get("environment")
    if not isinstance(raw, str) or not raw:
        raise GenerationSelectError("selection has no environment")
    environment = Path(raw).resolve()
    venv = _complete_venv(generation_dir)
    if environment != venv:
        raise GenerationSelectError("selection environment is not this generation's venv")
    return environment


def _fact_lock(fact: dict, generation_dir: Path) -> Path | None:
    raw = fact.get("resolved_lock")
    if raw is None or raw == "":
        fact.pop("resolved_lock", None)
        return None
    if not isinstance(raw, str):
        raise GenerationSelectError("selection lock is invalid")
    lock = Path(raw).resolve()
    expected = (generation_dir / "workspace" / "uv.lock").resolve()
    if lock != expected:
        raise GenerationSelectError("selection lock is not this generation's workspace lock")
    if not lock.is_file():
        # A generation can still boot from its venv when the workspace lock is gone.
        fact.pop("resolved_lock", None)
        return None
    return lock


def _require_fact(fact: object) -> dict:
    if not isinstance(fact, dict):
        raise GenerationSelectError("selection fact is invalid")
    extras = fact.get("extras")
    if (not isinstance(fact.get("stamp"), str) or not fact["stamp"]
            or not isinstance(extras, list) or any(not isinstance(extra, str) for extra in extras)):
        raise GenerationSelectError("selection fact is missing its stamp or extras")
    return fact


def _read_pin(generation_dir: Path, generation_id: str) -> dict:
    path = generation_dir / "selection.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise GenerationSelectError(
            f"generation {generation_id} has no pin; run `hermes pm generation pin` while it is selected"
        ) from exc
    except (OSError, ValueError) as exc:
        raise GenerationSelectError(f"generation {generation_id} pin cannot be read") from exc
    if not isinstance(data, dict) or data.get("schema") != 1 or data.get("generation") != generation_id:
        raise GenerationSelectError("selection record does not match this generation")
    return data


def _write_pin(generation_dir: Path, generation_id: str, fact: dict) -> None:
    from pm.filesystem import durable_write_bytes

    body = {"schema": 1, "generation": generation_id, "fact": fact}
    durable_write_bytes(
        generation_dir / "selection.json",
        (json.dumps(body, indent=2, sort_keys=True) + "\n").encode(),
    )


def pin_current_generation(project_root: Path) -> str:
    """Record the selected generation beside itself. Facts are only read."""
    from hermes_cli.runtime_state import runtime_lock
    from pm.lock import Facts
    from pm.environments import runtime_facts_path

    project = Path(project_root)
    with runtime_lock(project, timeout=None) as held:
        if not held:
            raise GenerationSelectError("could not lock the install state")
        fact = _require_fact(Facts(runtime_facts_path(project), strict=True).get("venv"))
        if not isinstance(fact.get("environment"), str) or not fact["environment"]:
            raise GenerationSelectError("selected environment is missing")
        environment = Path(fact["environment"]).resolve()
        generation_dir = environment.parent
        generation_id = _require_id(generation_dir.name)
        if generation_dir.resolve() != _generation_dir(project, generation_id).resolve():
            raise GenerationSelectError("selected environment is not one of this install's generations")
        _fact_environment(fact, generation_dir)
        _fact_lock(fact, generation_dir)
        _write_pin(generation_dir, generation_id, fact)
    return generation_id


def select_generation(project_root: Path, generation_id: str) -> str:
    """Point facts at a pinned, complete generation. The tree is not modified."""
    from hermes_cli.runtime_state import runtime_lock
    from pm.lock import Facts
    from pm.environments import runtime_facts_path
    from pm.packages import Venv

    project = Path(project_root)
    generation_id = _require_id(generation_id)
    with runtime_lock(project, timeout=None) as held:
        if not held:
            raise GenerationSelectError("could not lock the install state")
        generation_dir = _generation_dir(project, generation_id)
        fact = dict(_require_fact(_read_pin(generation_dir, generation_id).get("fact")))
        environment = _fact_environment(fact, generation_dir)
        lock = _fact_lock(fact, generation_dir)
        fact["stamp"] = Venv(project).expected_stamp(list(fact["extras"]))
        fact["environment"] = str(environment)
        if lock is not None:
            fact["resolved_lock"] = str(lock)
        Facts(runtime_facts_path(project), strict=True).replace_venv_fact(fact)
    return generation_id
