# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Trusted Foundation planners. They freeze plans; the journal executes them."""

from __future__ import annotations

import contextlib
import json
from pathlib import PurePosixPath
import re
import uuid

from _db import ensure_store, write_txn
from memory_fields import Document, validate_scope
from memory_io import (MANAGED_TYPES, MemoryBlocked, MemoryConflict, digest,
                       memory_lock, path_key, read_bytes, target, workspace)
import memory_journal as journal

PROTOCOL = "memory-operation-protocol: 1"
WRITER_SKILLS = ("memory-writing", "memory-repair", "memory-consolidation", "preference-update")


def compatibility():
    """Inspect the effective files and unresolved Phase B writes, without repair."""
    import skill_overrides
    root = workspace().parent
    failures = []
    for name in WRITER_SKILLS:
        path = root / "skills" / name / "SKILL.md"
        data = read_bytes(path)
        if data is None or skill_overrides._frontmatter(data.decode()).get("memory-operation-protocol") != "1" or b"apply_memory.py" not in data:
            failures.append(name + ": effective skill lacks memory protocol 1")
    # Called while the Phase B exclusive global lock is already held. Using
    # check_overrides() here would reacquire it and deadlock.
    for report, text in skill_overrides.snapshot_for_export(root, locked=True):
        if report.skill in WRITER_SKILLS and (report.kind != "applied" or (text is not None and PROTOCOL not in text)):
            failures.append(report.skill + ": unresolved skill override")
    return failures


def registered_resource(conn, path):
    keys = [path_key(path)]
    parts = PurePosixPath(path).parts
    if len(parts) == 3 and parts[0] == "projects":
        keys.append(path_key(str(PurePosixPath(path).parent / (parts[1] + ".md"))))
    return any(conn.execute("SELECT 1 FROM page_paths WHERE path_key=?", (key,)).fetchone() for key in keys)


@contextlib.contextmanager
def writer(*, check_skills=True, recover=True, expire=True):
    import skill_overrides
    # Phase B first. Taking the global exclusive barrier also makes checking
    # all effective skills one snapshot without per-skill lock inversion.
    with skill_overrides._global_lock(workspace().parent, exclusive=True):
        if check_skills:
            failures = compatibility()
            if failures:
                raise MemoryBlocked("; ".join(failures))
        with memory_lock(exclusive=True):
            ensure_store()
            if expire:
                journal.expire_locked()
            if recover:
                journal.recover_locked()
            yield


def enabled(conn):
    return bool(conn.execute("SELECT enabled FROM memory_control WHERE singleton=1").fetchone()[0])


def page(conn, page_id):
    row = conn.execute("SELECT * FROM pages WHERE page_id=?", (page_id,)).fetchone()
    if not row or row["state"] not in {"active", "retired"}:
        raise MemoryConflict("page is not registered and available")
    return dict(row)


def managed_path(path, *, generated=False):
    target(path)
    parts = PurePosixPath(path).parts
    if parts[0] not in MANAGED_TYPES:
        raise MemoryConflict("page type is outside the Foundation registry")
    if parts[0] == "projects":
        if len(parts) != 3 or parts[2] != parts[1] + ".md":
            raise MemoryConflict("project pages use projects/<slug>/<slug>.md")
    elif len(parts) != 2:
        raise MemoryConflict("invalid page layout")
    if generated and not all(re.fullmatch(r"[a-z0-9]+(?:_[a-z0-9]+)*", p.removesuffix(".md")) for p in parts[1:]):
        raise MemoryConflict("generated page names must use lowercase snake_case")
    return parts[0]


def available(conn, path, *, owner=None):
    key = path_key(path)
    prior = conn.execute("SELECT page_id FROM page_paths WHERE path_key=?", (key,)).fetchone()
    if prior and prior[0] != owner:
        raise MemoryConflict("path is reserved by another page")
    root = workspace() / "memory"
    if root.exists():
        for candidate in root.rglob("*"):
            relative = str(candidate.relative_to(root))
            if path_key(relative) == key and relative != path:
                raise MemoryConflict("case-folded path collision")
    if read_bytes(target(path)) is not None:
        raise MemoryConflict("destination already exists; existing content remains unmanaged")


def intrinsic_policy(name):
    return "additive" if name.startswith("entry:") else "write_once" if name in {
        "frontmatter:page_id", "frontmatter:id"} else "cas_protected"


def field_record(page_id, name, data, operation_id, *, origin="generated", policy=None):
    return {"page_id": page_id, "field_path": name, "content_origin": origin,
            "ownership_operation_id": operation_id, "review_operation_id": None,
            "ownership_policy": policy or intrinsic_policy(name), "last_content_hash": digest(data),
            "awaiting_first_review": int(origin == "adopted")}


def ownership(conn, field):
    """Foreign keys alone do not prove the actor, scope, or observed bytes."""
    op = conn.execute("SELECT * FROM page_operations WHERE operation_id=?",
                      (field["ownership_operation_id"],)).fetchone()
    if not op or op["status"] != "complete":
        raise MemoryConflict("ownership operation is not complete")
    effects = json.loads(op["effects_json"])["effects"]
    receipt = next((r for r in effects.get("fields", []) if r["page_id"] == field["page_id"]
                    and r["field_path"] == field["field_path"]), None)
    if not receipt or receipt["content_origin"] != field["content_origin"] or receipt["ownership_policy"] != field["ownership_policy"]:
        raise MemoryConflict("ownership receipt does not cover this field")
    if field["content_origin"] == "generated":
        if op["op_type"] not in {"create", "update"} or op["actor"] != "agent" or not receipt.get("absent_before"):
            raise MemoryConflict("generated field has no creation proof")
        if field["awaiting_first_review"] or field["review_operation_id"]:
            raise MemoryConflict("invalid generated ownership state")
    else:
        if op["op_type"] != "adopt" or op["actor"] != "user":
            raise MemoryConflict("adoption has no trusted user operation")
        if field["awaiting_first_review"]:
            raise MemoryConflict("adopted field awaits its first hash-specific review")
        review = conn.execute("SELECT * FROM page_operations WHERE operation_id=?", (field["review_operation_id"],)).fetchone()
        if not review or review["status"] != "complete" or review["actor"] != "user" or review["op_type"] != "review_adoption":
            raise MemoryConflict("adopted field has no completed user review")
        scopes = json.loads(review["effects_json"])["effects"].get("reviews", [])
        if not any(r["page_id"] == field["page_id"] and r["field_path"] == field["field_path"]
                   and r["hash"] == receipt["last_content_hash"] for r in scopes):
            raise MemoryConflict("review receipt does not cover the observed field")


def update_fields(conn, row, change, operation_id):
    if row["state"] != "active":
        raise MemoryConflict("retired pages are frozen")
    before = read_bytes(target(row["path"]))
    if before is None or digest(before) != change.get("expected_hash"):
        raise MemoryConflict("page precondition changed")
    doc = Document(before)
    existing = {r["field_path"]: dict(r) for r in conn.execute("SELECT * FROM managed_fields WHERE page_id=?", (row["page_id"],))}
    updates = change["fields"]
    if not isinstance(updates, dict) or (not updates and not change.get("sidecars")):
        raise MemoryConflict("update requires field changes or declared sidecar work")
    records = []
    encoded = {}
    for name, text in updates.items():
        if not isinstance(text, str):
            raise MemoryConflict("field replacement must be UTF-8 text")
        new = text.encode()
        old = doc.field(name)
        if name in existing:
            record = existing[name]
            ownership(conn, record)
            if digest(old) != record["last_content_hash"]:
                raise MemoryConflict("managed field was edited outside the protocol")
            if record["ownership_policy"] in {"write_once", "additive"} and old != new:
                raise MemoryConflict("immutable field or stable entry ID cannot be rewritten")
            record["last_content_hash"] = digest(new)
        else:
            if old is not None:
                raise MemoryConflict("existing field is unmanaged; preserve its bytes")
            if not enabled(conn):
                raise MemoryBlocked("automatic generated ownership is disabled")
            record = field_record(row["page_id"], name, new, operation_id)
            record["absent_before"] = True
        encoded[name] = new
        records.append(record)
    after = doc.render_fields(encoded)
    # Do not acquire overlapping ownership of an existing hand-managed or
    # generated nested section, even if the new outer heading was absent.
    policies = {k: r["ownership_policy"] for k, r in existing.items()}
    policies.update({r["field_path"]: r["ownership_policy"] for r in records})
    validate_scope(Document(after), policies)
    return (row["path"], before, after), records


def index_patch(before, changes):
    """Edit only the named entry lines and preserve all unrelated index bytes."""
    from memory_check import _parse_index
    if before is None:
        # Bootstrap's seed index references its attention pages. An independent
        # generated creation must not publish those references without pages.
        before = ("---\ntype: index\nupdated: 1970-01-01\n---\n\n# Memory index\n"
                  + "".join("\n## " + kind + "\n" for kind in
                            ("People", "Projects", "Patterns", "Concepts", "Goals", "Attention"))).encode()
    text = before.decode()
    parsed = _parse_index(text)
    if parsed.error or len(set(parsed.headings)) != len(parsed.headings):
        raise MemoryConflict("index structure is ambiguous; explicit repair required")
    for change in changes:
        path = change["path"]
        matches = [r for r in parsed.entries if r[0] == path]
        if len(matches) > 1:
            raise MemoryConflict("duplicate index entry")
        lines = text.splitlines(keepends=True)
        indices = [i for i, line in enumerate(lines)
                   if re.match(r"^- \[[^\]]+\]\(" + re.escape(path) + r"\)(?:\s|$)", line)]
        if matches and len(indices) != 1:
            raise MemoryConflict("index entry requires a reviewed multiline repair")
        # An entry's wrapped description belongs to the entry. Reject such
        # edits rather than leaving orphaned continuation text behind.
        if indices and indices[0] + 1 < len(lines) and lines[indices[0] + 1].startswith((" ", "\t")):
            raise MemoryConflict("multiline index entry requires an explicit repair")
        mode = change["mode"]
        if mode == "remove":
            if indices:
                del lines[indices[0]]
        elif mode == "retire":
            if not indices:
                raise MemoryConflict("cannot retire a missing index entry")
            lines[indices[0]] = lines[indices[0]].rstrip("\r\n") + " (retired)\n"
        elif mode == "rename":
            if not indices:
                raise MemoryConflict("cannot rename a missing index entry")
            lines[indices[0]] = lines[indices[0]].replace("(" + path + ")", "(" + change["to"] + ")")
        elif mode == "add":
            if indices:
                continue
            heading = "## " + path.split("/")[0].capitalize()
            starts = [i for i, line in enumerate(lines) if line.strip() == heading]
            if len(starts) != 1:
                raise MemoryConflict("index type section is missing or ambiguous")
            position = next((i for i in range(starts[0] + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
            label = change.get("label", PurePosixPath(path).stem.replace("_", " "))
            if not isinstance(label, str) or any(c in label for c in "[]()\r\n"):
                raise MemoryConflict("invalid index label")
            lines.insert(position, f"- [{label}]({path})\n")
        else:
            raise MemoryConflict("unknown index action")
        text = "".join(lines)
        parsed = _parse_index(text)
        if parsed.error:
            raise MemoryConflict("index patch would produce ambiguous structure")
    return text.encode()


def finish_plan(files, effects, index, operation_id, op_type):
    if index:
        before = read_bytes(target("index.md"))
        files.append(("index.md", before, index_patch(before, index)))
    before = read_bytes(target("log.md"))
    line = f"\n- {journal.stamp()} {op_type} <!-- mdcos:operation:{operation_id} -->\n".encode()
    files.append(("log.md", before, (before or b"# Memory log\n") + line))
    # Publish additions and changes before index references, remove references
    # before deletions. Each resource appears once in the frozen plan.
    if not effects.get("staged_rename"):
        files.sort(key=lambda f: 2 if f[2] is None else 1 if f[0] == "index.md" else 0)
    return files, effects


def _base_effects():
    return {"pages": [], "paths": [], "fields": [], "page_ids": []}


def _page_effect(row, **changes):
    return {key: changes.get(key, row[key]) for key in ("page_id", "path", "path_key", "state")} | {
        "expected_revision": row.get("revision", 0)}


def _path_effect(row, disposition="canonical"):
    return {key: row[key] for key in ("page_id", "path", "path_key")} | {"disposition": disposition}


def sidecar_updates(conn, row, changes, *, creating=False):
    """Append stable entries or rotate an exact prefix; never rewrite history."""
    if not changes:
        return [], []
    if row["page_type"] != "projects" or set(changes) - {"log.md", "rotate"}:
        raise MemoryConflict("only declared project logs are supported sidecars")
    known = set()
    for record in conn.execute("SELECT effects_json FROM page_operations WHERE status='complete'"):
        known.update(json.loads(record[0])["effects"].get("sidecars", {}).get(row["page_id"], []))
    files = []
    folder = PurePosixPath(row["path"]).parent
    if "log.md" in changes:
        item = changes["log.md"]
        exact(item, {"expected_hash", "entries"})
        path = str(folder / "log.md")
        before = read_bytes(target(path))
        if digest(before) != item["expected_hash"]:
            raise MemoryConflict("project log precondition changed")
        if before is not None and "log.md" not in known:
            raise MemoryConflict("existing project log is not owned")
        if before is None and not enabled(conn):
            raise MemoryBlocked("new generated project logs are disabled")
        after = before or b""
        doc = Document(after)
        for entry_id, text in item["entries"].items():
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", entry_id) or not isinstance(text, str):
                raise MemoryConflict("invalid project log entry")
            name = "entry:" + entry_id
            content = f"<!-- mdcos:entry:{entry_id} -->\n{text.rstrip()}\n<!-- /mdcos:entry:{entry_id} -->\n".encode()
            existing = doc.field(name)
            if existing is not None and existing != content:
                raise MemoryConflict("stable project log entry has different content")
            if existing is None:
                after = Document(after).render_fields({name: content})
                doc = Document(after)
        files.append((path, before, after))
        known.add("log.md")
    if "rotate" in changes:
        if "log.md" in changes:
            raise MemoryConflict("append and rotation must be separate bounded operations")
        item = changes["rotate"]
        exact(item, {"log_hash", "archive_hash", "entries"})
        log_path, archive_path = str(folder / "log.md"), str(folder / "log.archive.md")
        log, archive = read_bytes(target(log_path)), read_bytes(target(archive_path))
        if log is None or "log.md" not in known or (archive is not None and "log.archive.md" not in known):
            raise MemoryConflict("rotation requires owned project logs")
        if digest(log) != item["log_hash"] or digest(archive) != item["archive_hash"]:
            raise MemoryConflict("rotation precondition changed")
        doc = Document(log)
        entries = sorted((span.start, span.end, name) for name, span in doc.spans.items() if name.startswith("entry:"))
        count = item["entries"]
        if type(count) is not int or count < 1 or count > len(entries):
            raise MemoryConflict("rotation needs a nonempty bounded entry prefix")
        selected = entries[:count]
        if selected[0][0] != 0 or any(a[1] != b[0] for a, b in zip(selected, selected[1:])):
            raise MemoryConflict("rotation would move unowned bytes")
        archive_doc = Document(archive or b"")
        if any(name in archive_doc.spans for _, _, name in selected):
            raise MemoryConflict("archive already contains a selected entry ID")
        cut = selected[-1][1]
        files.extend([(archive_path, archive, (archive or b"") + log[:cut]), (log_path, log, log[cut:])])
        known.add("log.archive.md")
    return files, sorted(known)


def compile_agent(conn, envelope, operation_id):
    """Model-facing operation types. No lifecycle or metadata authority here."""
    action = envelope["action"]
    files, index, reservations = [], [], []
    effects = _base_effects()
    references = envelope.get("evidence_refs", [])
    if not isinstance(references, list) or len(references) > 128:
        raise MemoryConflict("evidence_refs must be a bounded list")
    for reference in references:
        if not isinstance(reference, str) or len(reference) > 512:
            raise MemoryConflict("invalid evidence reference")
        kind, separator, value = reference.partition(":")
        if not separator or kind not in {"item", "event"}:
            raise MemoryConflict("unknown evidence reference type")
        found = (conn.execute("SELECT 1 FROM items WHERE source_id=?", (value,)).fetchone() if kind == "item" else
                 conn.execute("SELECT 1 FROM events WHERE id=?", (value,)).fetchone())
        if not found:
            raise MemoryConflict("evidence reference does not exist in this store")
    effects["evidence_refs"] = references
    changes = envelope.get("changes", [])
    if action not in {"create", "update", "legacy_write", "log_only", "repair_index"}:
        raise MemoryConflict("action requires an explicit user command")
    maintenance_update = action == "update" and envelope.get("skill") in {"memory-repair", "memory-consolidation"}
    if action in {"create", "update"} and not enabled(conn) and not maintenance_update:
        raise MemoryBlocked("managed generation is disabled; run memory_operations.py enable")
    for change in changes:
        if action == "create":
            exact(change, {"path", "text", "fields"}, {"label", "sidecars"})
            path = change["path"]
            kind = managed_path(path, generated=True)
            available(conn, path)
            content = change["text"].encode()
            doc = Document(content)
            policies = {name: intrinsic_policy(name) for name in change["fields"]}
            if not policies:
                raise MemoryConflict("creation must declare generated fields")
            validate_scope(doc, policies)
            row = {"page_id": str(uuid.uuid4()), "page_type": kind, "path": path,
                   "path_key": path_key(path), "state": "active"}
            reservations.append(row)
            effects["page_ids"].append(row["page_id"])
            effects["pages"].append(_page_effect(row))
            effects["paths"].append(_path_effect(row))
            for name, policy in policies.items():
                record = field_record(row["page_id"], name, doc.field(name), operation_id, policy=policy)
                record["absent_before"] = True
                effects["fields"].append(record)
            files.append((path, None, content))
            side_files, names = sidecar_updates(conn, row, change.get("sidecars"), creating=True)
            files.extend(side_files)
            if names:
                effects.setdefault("sidecars", {})[row["page_id"]] = names
            index.append({"path": path, "mode": "add", "label": change.get("label", PurePosixPath(path).stem)})
        elif action == "update":
            exact(change, {"page_id", "expected_hash", "fields"}, {"sidecars"})
            row = page(conn, change["page_id"])
            file, records = update_fields(conn, row, change, operation_id)
            files.append(file)
            effects["fields"].extend(records)
            effects["page_ids"].append(row["page_id"])
            effects["pages"].append(_page_effect(row))
            side_files, names = sidecar_updates(conn, row, change.get("sidecars"))
            files.extend(side_files)
            if names:
                effects.setdefault("sidecars", {})[row["page_id"]] = names
        elif action == "legacy_write":
            exact(change, {"path", "expected_hash", "text"})
            path = change["path"]
            target(path)
            if path in {"index.md", "log.md"} or path.split("/")[0] == "goals":
                raise MemoryConflict("shared files need index/log actions; goals are user-owned")
            if registered_resource(conn, path):
                raise MemoryConflict("registered paths require field-aware updates")
            before = read_bytes(target(path))
            if digest(before) != change["expected_hash"]:
                raise MemoryConflict("legacy page precondition changed")
            if path.split("/")[0] in MANAGED_TYPES:
                if envelope.get("skill") not in {"memory-repair", "memory-consolidation"} or before is None:
                    raise MemoryConflict("unmanaged pages are only eligible for existing repair")
            after = None if change["text"] is None else change["text"].encode()
            files.append((path, before, after))
        else:
            raise MemoryConflict("this action accepts no page changes")
    if action == "legacy_write":
        for item in envelope.get("index", []):
            exact(item, {"path", "mode"}, {"label", "to"})
            affected = {f[0] for f in files}
            if item["path"] not in affected or item.get("to", item["path"]) not in affected:
                raise MemoryConflict("index patch must refer to affected legacy pages")
            after = next(f[2] for f in files if f[0] == item["path"])
            if item["mode"] not in {"add", "remove"} or (after is None) != (item["mode"] == "remove"):
                raise MemoryConflict("legacy index action must match the page's final presence")
            index.append(item)
        mentioned = {item["path"] for item in index}
        for path, before, after in files:
            if path not in mentioned and (before is None or after is None):
                index.append({"path": path, "mode": "remove" if after is None else "add"})
    elif action == "repair_index":
        for item in envelope.get("index", []):
            exact(item, {"path", "mode"}, {"label"})
            target(item["path"])
            exists = read_bytes(target(item["path"])) is not None
            if item["mode"] not in {"add", "remove"} or exists != (item["mode"] == "add"):
                raise MemoryConflict("index repair requires a verified present/absent target")
            index.append(item)
    elif envelope.get("index"):
        raise MemoryConflict("index patches are constructed by the managed planner")
    if action == "log_only" and changes:
        raise MemoryConflict("log-only operation cannot change a page")
    if references:
        for record in effects["fields"]:
            record["last_evidence_digest"] = journal.json_digest(references)
    return (*finish_plan(files, effects, index, operation_id, action), reservations)


def exact(value, required, optional=()):
    if not isinstance(value, dict) or not required <= value.keys() or value.keys() - required - set(optional):
        raise MemoryConflict("invalid or unsupported proposal fields")


def apply(envelope, *, fault=None, completion=()):
    """Apply an agent proposal; completion effects are code-only extension input."""
    exact(envelope, {"version", "store_instance_id", "request_id", "action"}, {"changes", "index", "skill", "evidence_refs"})
    if type(envelope["version"]) is not int or envelope["version"] != 1:
        raise MemoryConflict("unsupported memory proposal version")
    if not isinstance(envelope["request_id"], str) or not 1 <= len(envelope["request_id"]) <= 128:
        raise MemoryConflict("request_id must contain 1 to 128 characters")
    request_hash = journal.json_digest({"proposal": envelope, "completion": completion})
    with writer():
        prior = journal.lookup_request(envelope["request_id"], request_hash)
        if prior:
            return journal.result_for(prior)
        operation_id = str(uuid.uuid4())
        with journal.connection() as conn:
            files, effects, reservations = compile_agent(conn, envelope, operation_id)
        effects["completion"] = list(completion)
        journal.prepare(operation_id=operation_id, request_id=envelope["request_id"], request_digest=request_hash,
                        instance=envelope["store_instance_id"], op_type=envelope["action"], actor="agent",
                        files=files, effects=effects, reservations=reservations)
        if fault:
            fault("prepared", None)
        result = journal.recover_locked(fault=fault)
        result["page_ids"] = effects["page_ids"]
        return result
