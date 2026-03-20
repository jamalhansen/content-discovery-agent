import os
import sqlite3
import glob
import shutil
from datetime import datetime
import typer
from .config import SOCIAL_BLOCKED_DOMAINS
from . import store

def run_report(store_path: str, days: int):
    """Print a summary report of feed trends and scoring history."""
    store.init_db(store_path)
    conn = sqlite3.connect(store_path)
    try:
        # Total stats
        total = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
        kept = conn.execute("SELECT COUNT(*) FROM items WHERE status = 'kept'").fetchone()[0]
        dismissed = conn.execute("SELECT COUNT(*) FROM items WHERE status = 'dismissed'").fetchone()[0]
        pending = conn.execute("SELECT COUNT(*) FROM items WHERE status = 'new'").fetchone()[0]

        typer.echo(f"\n--- Content Discovery Report (Last {days} days) ---")
        typer.echo(f"Total items in DB: {total}")
        typer.echo(f"  Kept:      {kept}")
        typer.echo(f"  Dismissed: {dismissed}")
        typer.echo(f"  Pending:   {pending}")

        # Best sources
        typer.echo("\nTop Sources (by average score):")
        sources = conn.execute("""
            SELECT source, AVG(score) as avg_score, COUNT(*) as count
            FROM items
            GROUP BY source
            HAVING count > 5
            ORDER BY avg_score DESC
            LIMIT 10
        """).fetchall()
        for src, avg, count in sources:
            typer.echo(f"  {avg:.2f} ({count:3} items)  {src}")

    finally:
        conn.close()

def run_purge_blocked(store_path: str):
    """Dismiss pending items from blocked domains."""
    if not SOCIAL_BLOCKED_DOMAINS:
        typer.echo("No blocked domains configured.")
        return

    store.init_db(store_path)
    conn = sqlite3.connect(store_path)
    purged = 0
    try:
        pending = conn.execute("SELECT url FROM items WHERE status = 'new'").fetchall()
        for (url,) in pending:
            if any(domain in url for domain in SOCIAL_BLOCKED_DOMAINS):
                store.mark_item(url, "dismissed", store_path)
                purged += 1
        conn.commit()
    finally:
        conn.close()
    typer.echo(f"Purged {purged} items from blocked domains.")

def run_dismiss_source(query: str, store_path: str):
    """Dismiss pending items from a specific source."""
    store.init_db(store_path)
    conn = sqlite3.connect(store_path)
    try:
        count = conn.execute(
            "UPDATE items SET status = 'dismissed' WHERE status = 'new' AND source LIKE ?",
            (f"%{query}%",)
        ).rowcount
        conn.commit()
        typer.echo(f"Dismissed {count} pending items from sources matching '{query}'.")
    finally:
        conn.close()

def run_backup(store_path: str, backup_dir: str):
    """Back up the SQLite database."""
    db_path = os.path.expanduser(store_path)
    if not os.path.exists(db_path):
        typer.echo(f"Error: database not found at {db_path}", err=True)
        raise typer.Exit(1)

    dest_dir = os.path.expanduser(backup_dir)
    os.makedirs(dest_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    backup_path = os.path.join(dest_dir, f"content-discovery-{timestamp}.db")
    
    shutil.copy2(db_path, backup_path)
    size_kb = os.path.getsize(backup_path) / 1024
    typer.echo(f"Backed up to: {backup_path}")
    typer.echo(f"Size: {size_kb:.1f} KB")

def run_restore(file: str | None, latest: bool, store_path: str, backup_dir: str):
    """Restore the database from a backup."""
    db = os.path.expanduser(store_path)
    dest_dir = os.path.expanduser(backup_dir)
    
    if file:
        backup_path = os.path.expanduser(file)
        if not os.path.exists(backup_path):
            typer.echo(f"Error: backup file not found: {backup_path}", err=True)
            raise typer.Exit(1)
    else:
        pattern = os.path.join(dest_dir, "content-discovery-*.db")
        backups = sorted(glob.glob(pattern), reverse=True)
        if not backups:
            typer.echo(f"No backups found in {dest_dir}", err=True)
            raise typer.Exit(1)

        if latest:
            backup_path = backups[0]
            typer.echo(f"Most recent backup: {os.path.basename(backup_path)}")
        else:
            typer.echo("Available backups (newest first):\n")
            for i, b in enumerate(backups[:10], 1):
                size_kb = os.path.getsize(b) / 1024
                typer.echo(f"  [{i}] {os.path.basename(b)}  ({size_kb:.1f} KB)")
            typer.echo()
            choice = typer.prompt("Enter number to restore (or q to quit)")
            if choice.strip().lower() == "q":
                raise typer.Exit(0)
            try:
                idx = int(choice.strip()) - 1
                backup_path = backups[idx]
            except (ValueError, IndexError):
                typer.echo("Invalid selection.", err=True)
                raise typer.Exit(1)

    if not latest and not typer.confirm(f"Restore from {os.path.basename(backup_path)}? This will overwrite your current DB."):
        raise typer.Abort()

    shutil.copy2(backup_path, db)
    typer.echo("Database restored.")
