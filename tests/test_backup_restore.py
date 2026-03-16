"""Tests for the backup and restore CLI commands."""
import os
import sqlite3

from typer.testing import CliRunner

from content_discovery import app

runner = CliRunner()


def _make_db(path: str, n_items: int = 5) -> None:
    """Create a minimal items DB with n_items rows."""
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            score REAL NOT NULL DEFAULT 0.0,
            tags TEXT NOT NULL DEFAULT '[]',
            summary TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'new',
            fetched_at TEXT NOT NULL DEFAULT '',
            reviewed_at TEXT,
            published_at TEXT NOT NULL DEFAULT ''
        )
    """)
    for i in range(n_items):
        conn.execute(
            "INSERT OR IGNORE INTO items (url, title, status) VALUES (?,?,?)",
            (f"https://example.com/{i}", f"Item {i}", "kept"),
        )
    conn.commit()
    conn.close()


class TestBackupCommand:
    def test_creates_timestamped_backup(self, tmp_path):
        db = str(tmp_path / "store.db")
        backup_dir = str(tmp_path / "backups")
        _make_db(db)

        result = runner.invoke(app, [
            "backup", "--store", db, "--backup-dir", backup_dir,
        ])

        assert result.exit_code == 0, result.output
        files = os.listdir(backup_dir)
        assert len(files) == 1
        assert files[0].startswith("content-discovery-")
        assert files[0].endswith(".db")

    def test_output_includes_path_and_size(self, tmp_path):
        db = str(tmp_path / "store.db")
        backup_dir = str(tmp_path / "backups")
        _make_db(db)

        result = runner.invoke(app, [
            "backup", "--store", db, "--backup-dir", backup_dir,
        ])

        assert "Backed up to:" in result.output
        assert "Size:" in result.output

    def test_creates_backup_dir_if_missing(self, tmp_path):
        db = str(tmp_path / "store.db")
        backup_dir = str(tmp_path / "deep" / "nested" / "backups")
        _make_db(db)

        result = runner.invoke(app, [
            "backup", "--store", db, "--backup-dir", backup_dir,
        ])

        assert result.exit_code == 0
        assert os.path.isdir(backup_dir)

    def test_missing_db_exits_with_error(self, tmp_path):
        db = str(tmp_path / "nonexistent.db")
        backup_dir = str(tmp_path / "backups")

        result = runner.invoke(app, [
            "backup", "--store", db, "--backup-dir", backup_dir,
        ])

        assert result.exit_code == 1
        assert "not found" in result.output

    def test_multiple_backups_produce_distinct_files(self, tmp_path):
        import time
        db = str(tmp_path / "store.db")
        backup_dir = str(tmp_path / "backups")
        _make_db(db)

        runner.invoke(app, ["backup", "--store", db, "--backup-dir", backup_dir])
        time.sleep(1)  # ensure distinct timestamps
        runner.invoke(app, ["backup", "--store", db, "--backup-dir", backup_dir])

        files = os.listdir(backup_dir)
        assert len(files) == 2


class TestRestoreCommand:
    def _make_backup(self, backup_dir: str, name: str, n_items: int = 3) -> str:
        os.makedirs(backup_dir, exist_ok=True)
        path = os.path.join(backup_dir, name)
        _make_db(path, n_items=n_items)
        return path

    def test_dry_run_writes_nothing(self, tmp_path):
        db = str(tmp_path / "store.db")
        backup_dir = str(tmp_path / "backups")
        _make_db(db, n_items=5)
        self._make_backup(backup_dir, "content-discovery-2026-01-01-120000.db", n_items=3)

        result = runner.invoke(app, [
            "restore", "--store", db, "--backup-dir", backup_dir,
            "--latest", "--dry-run",
        ])

        assert result.exit_code == 0
        assert "dry-run" in result.output
        # DB unchanged — still has 5 items
        conn = sqlite3.connect(db)
        count = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
        conn.close()
        assert count == 5

    def test_latest_restores_most_recent(self, tmp_path):
        db = str(tmp_path / "store.db")
        backup_dir = str(tmp_path / "backups")
        _make_db(db, n_items=10)
        self._make_backup(backup_dir, "content-discovery-2026-01-01-120000.db", n_items=3)
        self._make_backup(backup_dir, "content-discovery-2026-02-01-120000.db", n_items=7)

        result = runner.invoke(app, [
            "restore", "--store", db, "--backup-dir", backup_dir,
            "--latest",
        ], input="yes\n")

        assert result.exit_code == 0, result.output
        assert "Restored" in result.output
        conn = sqlite3.connect(db)
        count = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
        conn.close()
        assert count == 7  # most recent backup had 7 items

    def test_restore_from_file(self, tmp_path):
        db = str(tmp_path / "store.db")
        backup_dir = str(tmp_path / "backups")
        _make_db(db, n_items=10)
        backup = self._make_backup(backup_dir, "content-discovery-2026-01-01-120000.db", n_items=4)

        result = runner.invoke(app, [
            "restore", "--store", db, "--backup-dir", backup_dir,
            "--file", backup,
        ], input="yes\n")

        assert result.exit_code == 0, result.output
        conn = sqlite3.connect(db)
        count = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
        conn.close()
        assert count == 4

    def test_aborted_without_yes_leaves_db_intact(self, tmp_path):
        db = str(tmp_path / "store.db")
        backup_dir = str(tmp_path / "backups")
        _make_db(db, n_items=10)
        self._make_backup(backup_dir, "content-discovery-2026-01-01-120000.db", n_items=3)

        result = runner.invoke(app, [
            "restore", "--store", db, "--backup-dir", backup_dir, "--latest",
        ], input="no\n")

        assert result.exit_code == 0
        assert "Aborted" in result.output
        conn = sqlite3.connect(db)
        count = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
        conn.close()
        assert count == 10  # untouched

    def test_creates_safety_backup_before_overwrite(self, tmp_path):
        db = str(tmp_path / "store.db")
        backup_dir = str(tmp_path / "backups")
        _make_db(db, n_items=10)
        self._make_backup(backup_dir, "content-discovery-2026-01-01-120000.db", n_items=3)

        runner.invoke(app, [
            "restore", "--store", db, "--backup-dir", backup_dir, "--latest",
        ], input="yes\n")

        files = os.listdir(backup_dir)
        safety_files = [f for f in files if "pre-restore" in f]
        assert len(safety_files) == 1

    def test_no_backups_exits_with_error(self, tmp_path):
        db = str(tmp_path / "store.db")
        backup_dir = str(tmp_path / "empty-backups")
        os.makedirs(backup_dir)
        _make_db(db)

        result = runner.invoke(app, [
            "restore", "--store", db, "--backup-dir", backup_dir, "--latest",
        ])

        assert result.exit_code == 1
        assert "No backups found" in result.output

    def test_shows_item_counts_for_both_dbs(self, tmp_path):
        db = str(tmp_path / "store.db")
        backup_dir = str(tmp_path / "backups")
        _make_db(db, n_items=10)
        self._make_backup(backup_dir, "content-discovery-2026-01-01-120000.db", n_items=3)

        result = runner.invoke(app, [
            "restore", "--store", db, "--backup-dir", backup_dir,
            "--latest", "--dry-run",
        ])

        assert "Backup DB" in result.output
        assert "Current DB" in result.output
