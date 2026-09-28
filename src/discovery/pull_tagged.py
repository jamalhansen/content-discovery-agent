"""Pull Reader items Jamal tagged for the vault into the Contexta inbox.

The reverse of routing: `run` sends discovered items to Reader, Jamal reads
them there, and tagging one (default tag ``contexta``) is his signal that it's
worth keeping. This writes each tagged item to inbox/ with his highlights and
Reader note, marked ``source_type: readwise-tagged`` so /reduce treats it as a
source he chose rather than an auto-discovered one.

After a successful pull (or when the item turns out to be captured already)
the tag is swapped to ``contexta-pulled`` on whichever Reader item carried it,
so Reader shows what has reached the vault. The ``source_url`` check against
notes/ and inbox/ (including inbox/archive/) stays as the backstop if a swap
fails.
"""
import os
import time
from dataclasses import dataclass, field

import requests
from local_first_common.url import normalize_url

from .import_reader import _already_captured_urls
from .vault_inbox import save_to_vault_inbox

_LIST_URL = "https://readwise.io/api/v3/list/"
_UPDATE_URL = "https://readwise.io/api/v3/update/{doc_id}/"
DEFAULT_TAG = "contexta"
PULLED_SUFFIX = "-pulled"
SOURCE_TYPE = "readwise-tagged"


@dataclass
class TaggedDoc:
    doc_id: str
    source_url: str
    title: str
    note: str = ""
    highlights: list[str] = field(default_factory=list)
    # (reader id, its current tag names) for each item that carries the tag:
    # the document itself, or a highlight on it.
    tag_holders: list[tuple[str, list[str]]] = field(default_factory=list)


@dataclass
class PullResult:
    tagged: int = 0
    already_captured: int = 0
    imported: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    retagged: int = 0
    retag_failed: list[str] = field(default_factory=list)


def list_reader_docs(token: str, **params) -> list[dict]:
    """All Reader documents matching ``params``, following pagination and 429s."""
    headers = {"Authorization": f"Token {token}"}
    docs: list[dict] = []
    cursor = None
    while True:
        query = dict(params)
        if cursor:
            query["pageCursor"] = cursor
        resp = requests.get(_LIST_URL, headers=headers, params=query, timeout=30)
        if resp.status_code == 429:
            time.sleep(int(resp.headers.get("Retry-After", "5")))
            continue
        resp.raise_for_status()
        data = resp.json()
        docs.extend(data.get("results") or [])
        cursor = data.get("nextPageCursor")
        if not cursor:
            return docs


def update_tags(token: str, doc_id: str, tags: list[str]) -> bool:
    """Replace a Reader item's tag list (the API takes the full list, not a delta)."""
    headers = {"Authorization": f"Token {token}"}
    for _ in range(3):
        resp = requests.patch(_UPDATE_URL.format(doc_id=doc_id), headers=headers, json={"tags": tags}, timeout=30)
        if resp.status_code == 429:
            time.sleep(int(resp.headers.get("Retry-After", "5")))
            continue
        return resp.ok
    return False


def _tag_names(doc: dict) -> list[str]:
    tags = doc.get("tags") or {}
    return list(tags.keys()) if isinstance(tags, dict) else list(tags)


def collect_tagged(token: str, tag: str = DEFAULT_TAG, list_docs=list_reader_docs) -> list[TaggedDoc]:
    """Tagged documents with their highlights attached.

    A tag placed on a highlight rather than its document counts as tagging the
    document. Highlights are fetched only when something is tagged.
    """
    tagged = list_docs(token, tag=tag)
    parent_ids = {d["parent_id"] for d in tagged if d.get("category") == "highlight" and d.get("parent_id")}
    by_id = {d["id"]: d for d in tagged if d.get("category") != "highlight"}
    missing = parent_ids - by_id.keys()
    if missing:
        for d in list_docs(token, id=",".join(sorted(missing))):
            by_id[d["id"]] = d
    if not by_id:
        return []

    highlights: dict[str, list[tuple[int, str]]] = {}
    for h in list_docs(token, category="highlight"):
        pid = h.get("parent_id")
        if pid in by_id and (h.get("content") or "").strip():
            highlights.setdefault(pid, []).append((h.get("highlight_location") or 0, h["content"].strip()))

    holders: dict[str, list[tuple[str, list[str]]]] = {}
    for d in tagged:
        owner = d.get("parent_id") if d.get("category") == "highlight" else d["id"]
        if owner in by_id:
            holders.setdefault(owner, []).append((d["id"], _tag_names(d)))

    return [
        TaggedDoc(
            doc_id=doc_id,
            source_url=d.get("source_url") or d.get("url") or "",
            title=d.get("title") or "(untitled)",
            note=(d.get("notes") or "").strip(),
            highlights=[text for _, text in sorted(highlights.get(doc_id, []))],
            tag_holders=holders.get(doc_id, []),
        )
        for doc_id, d in by_id.items()
    ]


def _mark_pulled(token: str, doc: TaggedDoc, tag: str, update, result: PullResult) -> None:
    done = tag + PULLED_SUFFIX
    for item_id, names in doc.tag_holders:
        new = [n for n in names if n != tag]
        if done not in new:
            new.append(done)
        if update(token, item_id, new):
            result.retagged += 1
        else:
            result.retag_failed.append(doc.title)


def pull_tagged_items(
    notes_path: str,
    inbox_path: str,
    token: str,
    *,
    tag: str = DEFAULT_TAG,
    limit: int = 20,
    dry_run: bool = False,
    list_docs=list_reader_docs,
    save=save_to_vault_inbox,
    update=update_tags,
) -> PullResult:
    result = PullResult()
    captured = _already_captured_urls(notes_path, inbox_path)
    for doc in collect_tagged(token, tag, list_docs=list_docs):
        result.tagged += 1
        if not doc.source_url:
            result.failed.append(doc.title)
            continue
        try:
            key = normalize_url(doc.source_url)
        except Exception:  # noqa: BLE001 - dedupe a malformed URL on its raw form rather than crash
            key = doc.source_url
        if key in captured:
            result.already_captured += 1
            if not dry_run:
                _mark_pulled(token, doc, tag, update, result)
            continue
        if len(result.imported) + len(result.failed) >= limit:
            continue
        if dry_run:
            result.imported.append(doc.title)
            continue
        ok = save(
            os.path.expanduser(inbox_path),
            doc.source_url,
            doc.title,
            platform="readwise-reader",
            source_type=SOURCE_TYPE,
            highlights=doc.highlights,
            reader_note=doc.note,
        )
        if ok:
            result.imported.append(doc.title)
            captured.add(key)
            _mark_pulled(token, doc, tag, update, result)
        else:
            result.failed.append(doc.title)
    return result
