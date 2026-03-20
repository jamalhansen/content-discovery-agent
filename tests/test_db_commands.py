"""Tests for db_commands.py — report, purge, backup/restore logic."""

import os
import sqlite3
import shutil
from unittest.mock import patch

import pytest
import typer
from discovery import db_commands, store


@pytest.fixture
def mock_db(tmp_path):
    db_path = tmp_path / "test.db"
    store.init_db(str(db_path))
    return str(db_path)


def test_run_report_empty(mock_db):
    """Report runs on empty DB."""
    db_commands.run_report(mock_db, 7)


def test_run_report_with_data(mock_db):
    """Report shows counts and top sources."""
    conn = sqlite3.connect(mock_db)
    # url, title, source, score, fetched_at are NOT NULL
    for i in range(6):
        conn.execute(
            "INSERT INTO items (url, title, source, score, fetched_at, status) VALUES (?, ?, ?, ?, ?, ?)",
            (f"url{i}", f"t{i}", "source1", 0.9, "2026-03-20", "kept")
        )
    conn.commit()
    conn.close()
    
    db_commands.run_report(mock_db, 7)


def test_run_purge_blocked_no_config(mock_db):
    """Purge returns early if no blocked domains."""
    with patch("discovery.db_commands.SOCIAL_BLOCKED_DOMAINS", []):
        db_commands.run_purge_blocked(mock_db)


def test_run_purge_blocked_with_data(mock_db):
    """Dismisses items from blocked domains."""
    with patch("discovery.db_commands.SOCIAL_BLOCKED_DOMAINS", ["spam.com"]):
        conn = sqlite3.connect(mock_db)
        conn.execute(
            "INSERT INTO items (url, title, source, score, fetched_at, status) VALUES (?, ?, ?, ?, ?, ?)",
            ("http://spam.com/1", "Spam", "src", 0.1, "2026-03-20", "new")
        )
        conn.execute(
            "INSERT INTO items (url, title, source, score, fetched_at, status) VALUES (?, ?, ?, ?, ?, ?)",
            ("http://good.com/1", "Good", "src", 0.8, "2026-03-20", "new")
        )
        conn.commit()
        conn.close()
        
        db_commands.run_purge_blocked(mock_db)
        
        conn = sqlite3.connect(mock_db)
        spam_status = conn.execute("SELECT status FROM items WHERE url LIKE '%spam.com%'").fetchone()[0]
        good_status = conn.execute("SELECT status FROM items WHERE url LIKE '%good.com%'").fetchone()[0]
        assert spam_status == "dismissed"
        assert good_status == "new"
        conn.close()


def test_run_dismiss_source(mock_db):
    """Dismisses items from matching source."""
    conn = sqlite3.connect(mock_db)
    conn.execute(
        "INSERT INTO items (url, title, source, score, fetched_at, status) VALUES (?, ?, ?, ?, ?, ?)",
        ("u1", "t1", "Bluesky: keywords", 0.5, "2026-03-20", "new")
    )
    conn.commit()
    conn.close()
    
    db_commands.run_dismiss_source("Bluesky", mock_db)
    
    conn = sqlite3.connect(mock_db)
    status = conn.execute("SELECT status FROM items").fetchone()[0]
    assert status == "dismissed"
    conn.close()


def test_run_backup_not_found(tmp_path):
    """Error if DB not found."""
    with pytest.raises(typer.Exit):
        db_commands.run_backup(str(tmp_path / "missing.db"), str(tmp_path / "backups"))


def test_run_backup_success(mock_db, tmp_path):
    """Creates a backup file."""
    backup_dir = tmp_path / "backups"
    db_commands.run_backup(mock_db, str(backup_dir))
    
    assert backup_dir.exists()
    backups = list(backup_dir.glob("content-discovery-*.db"))
    assert len(backups) == 1


def test_run_restore_latest(mock_db, tmp_path):
    """Restores latest backup."""
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    backup_file = backup_dir / "content-discovery-2026-03-20-120000.db"
    shutil.copy2(mock_db, backup_file)
    
    # Modify original DB
    conn = sqlite3.connect(mock_db)
    conn.execute("DELETE FROM items")
    conn.commit()
    conn.close()
    
    db_commands.run_restore(None, True, mock_db, str(backup_dir))
    assert os.path.exists(mock_db)


@patch("typer.prompt")
def test_run_restore_selection(mock_prompt, mock_db, tmp_path):
    """Restores selected backup."""
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    backup_file = backup_dir / "content-discovery-2026-03-20-120000.db"
    shutil.copy2(mock_db, backup_file)
    
    mock_prompt.return_value = "1"
    with patch("typer.confirm", return_value=True):
        db_commands.run_restore(None, False, mock_db, str(backup_dir))
    
    assert os.path.exists(mock_db)
