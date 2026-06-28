"""Reproducibility & provenance.

No experiment result is accepted without provenance (fail-closed policy). Every
run stamps: git commit, data hash, feature/code versions, config hash, seed,
environment, dependency-lock hash, artifact path, and an immutable run id. Two
runs with the same provenance must reproduce the same metrics.
"""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
import uuid
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .config import SETTINGS

__all__ = ["RunProvenance", "sha256_bytes", "sha256_file", "sha256_obj", "git_commit", "capture"]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_obj(obj: object) -> str:
    return sha256_bytes(json.dumps(obj, sort_keys=True, default=str).encode())


def git_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5, check=True
        )
        return out.stdout.strip()
    except Exception:
        return "unknown"


@dataclass(frozen=True, slots=True)
class RunProvenance:
    run_id: str
    git_commit: str
    data_hash: str
    feature_version: str
    code_version: str
    config_hash: str
    random_seed: int
    python_version: str
    platform: str
    dependency_lock_hash: str
    artifact_path: str | None = None
    extra: Mapping[str, str] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True)


def capture(
    *,
    data_hash: str,
    config: Mapping[str, object],
    random_seed: int,
    artifact_path: str | None = None,
    lockfile: Path | None = None,
    feature_version: str = SETTINGS.feature_version,
    code_version: str = SETTINGS.code_version,
    extra: Mapping[str, str] | None = None,
) -> RunProvenance:
    """Capture full provenance for a run. `data_hash` must come from the dataset used."""
    return RunProvenance(
        run_id=uuid.uuid4().hex,
        git_commit=git_commit(),
        data_hash=data_hash,
        feature_version=feature_version,
        code_version=code_version,
        config_hash=sha256_obj(dict(config)),
        random_seed=random_seed,
        python_version=sys.version.split()[0],
        platform=platform.platform(),
        dependency_lock_hash=sha256_file(lockfile) if lockfile and lockfile.exists() else "none",
        artifact_path=artifact_path,
        extra=dict(extra or {}),
    )
