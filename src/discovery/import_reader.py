"""Pull existing Readwise Reader items into the Contexta inbox.

`reconcile` closes the loop from the vault side: a note with `source_url`
archives its Reader copy. This module is the other direction, for the backlog
that predates the tool or was never routed through it. Reader accumulated
hundreds of unread items before any of this existed; `run` only routes items
it fetches itself, so nothing pulls the existing queue into the vault on its
own.

An item already captured, whether it became a note or is still sitting in
inbox/ unreduced, is skipped. Skipping is decided by `source_url`, using the
same frontmatter convention and normalized-URL matching as `reconcile`, read
from both notes/ and inbox/ (including inbox/archive/) so a file that has not
been through /reduce yet does not get fetched a second time.
"""
import os
from dataclasses import dataclass, field

from local_first_common.url import normalize_url

from .reconcile import collect_note_source_urls
from .vault_inbox import save_to_vault_inbox


@dataclass
class ImportResult:
    documents_checked: int = 0
    already_captured: int = 0
    imported: list[str] = field(default_factory=list)  # titles
    failed: list[str] = field(default_factory=list)  # titles that would not write


def _already_captured_urls(*dirs: str) -> set[str]:
    seen: set[str] = set()
    for d in dirs:
        seen |= set(collect_note_source_urls(d).keys())
        archive = os.path.join(os.path.expanduser(d), "archive")
        if os.path.isdir(archive):
            seen |= set(collect_note_source_urls(archive).keys())
    return seen


def import_reader_backlog(
    notes_path: str,
    inbox_path: str,
    token: str,
    *,
    locations: tuple[str, ...] = ("new", "later"),
    limit: int = 10,
    dry_run: bool = False,
    list_refs=None,
    save=None,
) -> ImportResult:
    """Write unread Reader items not yet captured anywhere into the inbox.

    ``limit`` bounds how many articles get fetched in one call, since each is a
    live HTTP request against a page of unknown size. ``list_refs`` and
    ``save`` are injectable for testing; they default to the shared Readwise
    helper and ``save_to_vault_inbox``.
    """
    if list_refs is None:
        from local_first_common.readwise import list_reader_refs

        list_refs = list_reader_refs
    if save is None:
        save = save_to_vault_inbox

    result = ImportResult()
    captured = _already_captured_urls(notes_path, inbox_path)

    seen_docs: set[str] = set()
    for location in locations:
        for ref in list_refs(token, location=location):
            if ref.doc_id in seen_docs:
                continue
            seen_docs.add(ref.doc_id)
            result.documents_checked += 1

            try:
                key = normalize_url(ref.source_url)
            except Exception:
                key = ref.source_url
            if key in captured:
                result.already_captured += 1
                continue

            if len(result.imported) + len(result.failed) >= limit:
                continue

            if dry_run:
                result.imported.append(ref.title)
                continue

            ok = save(inbox_path, ref.source_url, ref.title, platform="readwise-reader")
            if ok:
                result.imported.append(ref.title)
                captured.add(key)
            else:
                result.failed.append(ref.title)

    return result
