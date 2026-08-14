"""Provenance manifest for the snapshot archive.

The archive is the one part of this project that cannot be regenerated.
Oregon rotates old quarters off its site and CalPERS publishes only the
current table, so a snapshot that is lost or silently altered is gone. The
manifest records what each file is and what it hashed to, which makes three
questions answerable later:

*   Did this file change? A re-download that returns different bytes for the
    same quarter means the plan restated something, and a restatement changes
    reconstructed cash flows. Comparing hashes surfaces that; comparing file
    sizes or dates does not.
*   Where did this row count come from? A parser change that silently drops
    funds shows up as a row count moving without the hash moving.
*   When was it captured? Reporting lag matters for interpreting a snapshot,
    and the download time is not recoverable from the file afterwards.

`download_timestamp` is preserved across rebuilds for files whose hash has not
changed. Rebuilding the manifest is a bookkeeping operation and must not
rewrite the capture history; without this, regenerating would stamp every file
with today's date and destroy exactly the provenance the file exists to hold.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

MANIFEST_NAME = "MANIFEST.csv"

MANIFEST_COLUMNS = [
    "filename",
    "kind",
    "source",
    "as_of",
    "download_timestamp",
    "sha256",
    "rows",
]

#: Quarter-end dates, so a raw PDF can be dated from its filename without
#: reopening it.
_QUARTER_END = {1: "03-31", 2: "06-30", 3: "09-30", 4: "12-31"}
_RAW_QUARTER = re.compile(r"(\d{4})Q([1-4])")
_SNAPSHOT_DATE = re.compile(r"_(\d{4}-\d{2}-\d{2})\.csv$")

_SOURCE_BY_PREFIX = {
    "oregon": "Oregon PERS OPERF",
    "calpers": "CalPERS PEP",
}


def sha256_of(path: str | Path, chunk_size: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_for(name: str) -> str:
    for prefix, source in _SOURCE_BY_PREFIX.items():
        if name.lower().startswith(prefix) or f"_{prefix}" in name.lower():
            return source
    return "unknown"


def _as_of_for(path: Path) -> str:
    """Reporting date, from the filename in both naming schemes."""
    match = _SNAPSHOT_DATE.search(path.name)
    if match:
        return match.group(1)
    match = _RAW_QUARTER.search(path.name)
    if match:
        year, quarter = match.group(1), int(match.group(2))
        return f"{year}-{_QUARTER_END[quarter]}"
    return ""


def archive_files(snapshots_dir: str | Path) -> list[tuple[Path, str]]:
    """Every archived file, as (path, kind), in a stable order."""
    root = Path(snapshots_dir)
    snapshots = [(p, "snapshot") for p in sorted(root.glob("*.csv"))
                 if p.name != MANIFEST_NAME]
    raw = [(p, "raw") for p in sorted((root / "raw").glob("*"))
           if p.is_file() and not p.name.startswith(".")]
    return snapshots + raw


def build_manifest(
    snapshots_dir: str | Path, existing: pd.DataFrame | None = None
) -> pd.DataFrame:
    """Describe the archive. Reads files; never writes or deletes them."""
    root = Path(snapshots_dir)
    if existing is None:
        existing = read_manifest(root)
    known = (
        dict(zip(existing["filename"], zip(existing["sha256"], existing["download_timestamp"])))
        if not existing.empty
        else {}
    )

    rows = []
    for path, kind in archive_files(root):
        name = str(path.relative_to(root))
        digest = sha256_of(path)

        # Keep the original capture time unless the bytes actually changed.
        previous = known.get(name)
        if previous is not None and previous[0] == digest:
            captured = previous[1]
        else:
            captured = datetime.fromtimestamp(
                path.stat().st_mtime, tz=timezone.utc
            ).isoformat(timespec="seconds")

        row_count = ""
        if kind == "snapshot":
            row_count = int(sum(1 for _ in open(path, encoding="utf-8")) - 1)

        rows.append(
            {
                "filename": name,
                "kind": kind,
                "source": _source_for(path.name),
                "as_of": _as_of_for(path),
                "download_timestamp": captured,
                "sha256": digest,
                "rows": row_count,
            }
        )

    return pd.DataFrame(rows, columns=MANIFEST_COLUMNS)


def read_manifest(snapshots_dir: str | Path) -> pd.DataFrame:
    path = Path(snapshots_dir) / MANIFEST_NAME
    if not path.exists():
        return pd.DataFrame(columns=MANIFEST_COLUMNS)
    return pd.read_csv(path, dtype=str).fillna("")


def write_manifest(snapshots_dir: str | Path) -> pd.DataFrame:
    """Rebuild and save the manifest. Idempotent."""
    manifest = build_manifest(snapshots_dir)
    manifest.to_csv(Path(snapshots_dir) / MANIFEST_NAME, index=False)
    return manifest


def verify_manifest(snapshots_dir: str | Path) -> dict[str, list[str]]:
    """Compare the manifest against what is on disk.

    Returns lists under `missing` (in the manifest, absent from disk),
    `untracked` (on disk, absent from the manifest) and `changed` (present in
    both, different hash). An empty value for all three means the archive is
    exactly what was recorded.
    """
    root = Path(snapshots_dir)
    recorded = read_manifest(root)
    on_disk = {str(p.relative_to(root)): sha256_of(p) for p, _ in archive_files(root)}

    recorded_hashes = dict(zip(recorded["filename"], recorded["sha256"]))
    return {
        "missing": sorted(set(recorded_hashes) - set(on_disk)),
        "untracked": sorted(set(on_disk) - set(recorded_hashes)),
        "changed": sorted(
            name
            for name, digest in on_disk.items()
            if name in recorded_hashes and recorded_hashes[name] != digest
        ),
    }
