"""Tests for the snapshot provenance manifest.

The manifest exists to make three failures visible: a restated snapshot, a
parser that silently drops rows, and a lost capture date. Each test below
corresponds to one of those.
"""

from pathlib import Path

import pandas as pd
import pytest

from pefund.ingest.manifest import (
    MANIFEST_COLUMNS,
    archive_files,
    build_manifest,
    read_manifest,
    sha256_of,
    verify_manifest,
    write_manifest,
)

REPO_SNAPSHOTS = Path(__file__).resolve().parents[1] / "data" / "snapshots"


@pytest.fixture
def archive(tmp_path):
    """A miniature archive with one snapshot CSV and one raw file."""
    (tmp_path / "raw").mkdir()
    (tmp_path / "oregon_2024-03-31.csv").write_text(
        "fund_id,vintage\nOPERF::A,2019\nOPERF::B,2020\n"
    )
    (tmp_path / "calpers_2026-08-13.csv").write_text("fund_id,vintage\nCALPERS::C,2001\n")
    (tmp_path / "raw" / "oregon_operf_pe_2024Q1.pdf").write_bytes(b"%PDF-1.4 fake")
    return tmp_path


class TestManifestContents:
    def test_covers_snapshots_and_raw_files(self, archive):
        manifest = build_manifest(archive)
        assert len(manifest) == 3
        assert set(manifest["kind"]) == {"snapshot", "raw"}

    def test_columns_are_the_declared_schema(self, archive):
        assert list(build_manifest(archive).columns) == MANIFEST_COLUMNS

    def test_row_counts_exclude_the_header(self, archive):
        manifest = build_manifest(archive).set_index("filename")
        assert manifest.loc["oregon_2024-03-31.csv", "rows"] == 2
        assert manifest.loc["calpers_2026-08-13.csv", "rows"] == 1

    def test_raw_files_have_no_row_count(self, archive):
        manifest = build_manifest(archive).set_index("kind")
        assert manifest.loc["raw", "rows"] == ""

    def test_source_is_inferred_from_the_filename(self, archive):
        manifest = build_manifest(archive).set_index("filename")
        assert manifest.loc["oregon_2024-03-31.csv", "source"] == "Oregon PERS OPERF"
        assert manifest.loc["calpers_2026-08-13.csv", "source"] == "CalPERS PEP"

    def test_as_of_is_read_from_both_naming_schemes(self, archive):
        manifest = build_manifest(archive).set_index("filename")
        assert manifest.loc["oregon_2024-03-31.csv", "as_of"] == "2024-03-31"
        # Raw PDFs are named by quarter, which maps to the quarter-end date.
        assert manifest.loc["raw/oregon_operf_pe_2024Q1.pdf", "as_of"] == "2024-03-31"

    def test_hash_matches_the_file(self, archive):
        manifest = build_manifest(archive).set_index("filename")
        expected = sha256_of(archive / "oregon_2024-03-31.csv")
        assert manifest.loc["oregon_2024-03-31.csv", "sha256"] == expected


class TestIdempotence:
    def test_rebuilding_changes_nothing(self, archive):
        first = write_manifest(archive)
        second = write_manifest(archive)
        pd.testing.assert_frame_equal(first, second)

    def test_capture_time_survives_a_rebuild(self, archive):
        first = write_manifest(archive).set_index("filename")
        second = write_manifest(archive).set_index("filename")
        # If this drifted, rebuilding the manifest would erase the provenance
        # the manifest exists to hold.
        assert (
            first.loc["oregon_2024-03-31.csv", "download_timestamp"]
            == second.loc["oregon_2024-03-31.csv", "download_timestamp"]
        )

    def test_capture_time_updates_only_when_bytes_change(self, archive):
        before = write_manifest(archive).set_index("filename")
        target = archive / "oregon_2024-03-31.csv"
        target.write_text("fund_id,vintage\nOPERF::A,2019\nOPERF::B,2020\nOPERF::C,2021\n")
        after = write_manifest(archive).set_index("filename")

        assert after.loc["oregon_2024-03-31.csv", "sha256"] != (
            before.loc["oregon_2024-03-31.csv", "sha256"]
        )
        assert after.loc["oregon_2024-03-31.csv", "rows"] == 3
        # The untouched file keeps its original capture time.
        assert (
            after.loc["calpers_2026-08-13.csv", "download_timestamp"]
            == before.loc["calpers_2026-08-13.csv", "download_timestamp"]
        )

    def test_building_never_writes_or_deletes_snapshots(self, archive):
        before = {p.name: sha256_of(p) for p, _ in archive_files(archive)}
        write_manifest(archive)
        write_manifest(archive)
        after = {p.name: sha256_of(p) for p, _ in archive_files(archive)}
        assert before == after

    def test_manifest_excludes_itself(self, archive):
        write_manifest(archive)
        manifest = write_manifest(archive)
        assert "MANIFEST.csv" not in set(manifest["filename"])


class TestVerification:
    def test_clean_archive_verifies(self, archive):
        write_manifest(archive)
        assert verify_manifest(archive) == {
            "missing": [], "untracked": [], "changed": []
        }

    def test_altered_file_is_reported_as_changed(self, archive):
        write_manifest(archive)
        (archive / "oregon_2024-03-31.csv").write_text("fund_id,vintage\nOPERF::Z,1999\n")
        assert verify_manifest(archive)["changed"] == ["oregon_2024-03-31.csv"]

    def test_new_file_is_reported_as_untracked(self, archive):
        write_manifest(archive)
        (archive / "oregon_2024-06-30.csv").write_text("fund_id,vintage\nOPERF::D,2021\n")
        assert verify_manifest(archive)["untracked"] == ["oregon_2024-06-30.csv"]

    def test_deleted_file_is_reported_as_missing(self, archive):
        write_manifest(archive)
        (archive / "calpers_2026-08-13.csv").unlink()
        assert verify_manifest(archive)["missing"] == ["calpers_2026-08-13.csv"]

    def test_missing_manifest_reads_as_empty_not_an_error(self, tmp_path):
        (tmp_path / "raw").mkdir()
        assert read_manifest(tmp_path).empty


class TestShippedArchive:
    """The real archive in this repository must match its manifest."""

    def test_repository_archive_verifies(self):
        if not (REPO_SNAPSHOTS / "MANIFEST.csv").exists():
            pytest.skip("no snapshot archive in this checkout")
        result = verify_manifest(REPO_SNAPSHOTS)
        assert result == {"missing": [], "untracked": [], "changed": []}, (
            f"snapshot archive does not match its manifest: {result}"
        )

    def test_every_snapshot_has_a_source_and_a_date(self):
        if not (REPO_SNAPSHOTS / "MANIFEST.csv").exists():
            pytest.skip("no snapshot archive in this checkout")
        manifest = read_manifest(REPO_SNAPSHOTS)
        assert (manifest["source"] != "unknown").all()
        assert (manifest["as_of"] != "").all()
