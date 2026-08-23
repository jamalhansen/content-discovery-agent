"""Reconcile the Readwise Reader queue against notes already written to the vault.

The Reader integration used to be write-only: items were pushed in and nothing
ever took them out, so the unread queue grew for four months while the same
articles were separately being turned into vault notes. Nothing linked the two.

A note that carries ``source_url`` in its frontmatter is a read receipt: that
article has been read closely enough to make a claim out of it, so its Reader
copy is finished. This module finds those receipts and archives the matching
documents.

Matching is on normalized URL, so a note whose ``source_url`` differs only by
tracking parameters or a trailing slash still counts.
"""
import os
import re
from dataclasses import dataclass, field

from local_first_common.url import normalize_url

# Frontmatter lives between the first two `---` fences. Only the first block is
# read, so a `source_url:` mentioned in the body is not mistaken for the field.
_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_SOURCE_URL_RE = re.compile(r"^source_url:\s*(.+?)\s*$", re.MULTILINE)


@dataclass
class ReconcileResult:
    notes_scanned: int = 0
    notes_with_source_url: int = 0
    # Several notes routinely come from one article, so this is always <= the
    # count above and is the number that explains how many documents can match.
    distinct_source_urls: int = 0
    documents_checked: int = 0
    matched: list[tuple[str, str]] = field(default_factory=list)  # (title, source_url)
    archived: int = 0
    failed: list[str] = field(default_factory=list)  # doc_ids that would not archive


def extract_source_url(text: str) -> str:
    """Return the source_url from a note's frontmatter, or "" if absent.

    Tolerates quoted and unquoted values. An empty value (the template default)
    is treated as absent rather than as a URL.
    """
    block = _FRONTMATTER_RE.match(text)
    if not block:
        return ""
    found = _SOURCE_URL_RE.search(block.group(1))
    if not found:
        return ""
    return found.group(1).strip().strip('"').strip("'")


def collect_note_source_urls(notes_path: str) -> dict[str, list[str]]:
    """Map normalized source_url to the notes that cite it.

    A single article usually yields several notes, so the value is a list. The
    mapping is keyed by URL because that is what a Reader document is matched on.
    """
    urls: dict[str, list[str]] = {}
    target = os.path.expanduser(notes_path)
    if not os.path.isdir(target):
        return urls

    for name in sorted(os.listdir(target)):
        if not name.endswith(".md"):
            continue
        try:
            with open(os.path.join(target, name)) as f:
                text = f.read()
        except OSError:
            continue
        raw = extract_source_url(text)
        if not raw:
            continue
        try:
            key = normalize_url(raw)
        except Exception:
            key = raw
        urls.setdefault(key, []).append(name)
    return urls


def reconcile(
    notes_path: str,
    token: str,
    *,
    locations: tuple[str, ...] = ("new", "later"),
    dry_run: bool = False,
    list_refs=None,
    archive=None,
) -> ReconcileResult:
    """Archive Reader documents whose article already became a vault note.

    ``list_refs`` and ``archive`` are injectable for testing; they default to the
    shared Readwise helpers.
    """
    if list_refs is None or archive is None:
        from local_first_common.readwise import archive_reader_document, list_reader_refs

        list_refs = list_refs or list_reader_refs
        archive = archive or archive_reader_document

    result = ReconcileResult()
    note_urls = collect_note_source_urls(notes_path)
    result.distinct_source_urls = len(note_urls)
    result.notes_with_source_url = sum(len(v) for v in note_urls.values())
    target = os.path.expanduser(notes_path)
    result.notes_scanned = (
        sum(1 for n in os.listdir(target) if n.endswith(".md"))
        if os.path.isdir(target) else 0
    )

    seen: set[str] = set()
    for location in locations:
        for ref in list_refs(token, location=location):
            if ref.doc_id in seen:
                continue
            seen.add(ref.doc_id)
            result.documents_checked += 1
            try:
                key = normalize_url(ref.source_url)
            except Exception:
                key = ref.source_url
            if key not in note_urls:
                continue
            result.matched.append((ref.title, ref.source_url))
            if dry_run:
                continue
            if archive(token, ref.doc_id):
                result.archived += 1
            else:
                result.failed.append(ref.doc_id)

    return result
