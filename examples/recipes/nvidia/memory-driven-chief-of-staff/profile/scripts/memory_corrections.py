# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Explicit page actions reached through correct.py, never an agent envelope."""

from __future__ import annotations

import json
from pathlib import PurePosixPath
import posixpath
import re
import uuid

from _db import write_txn
from memory_fields import Document, validate_scope
from memory_io import MemoryBlocked, MemoryConflict, digest, path_key, read_bytes, target, workspace
import memory_journal as journal
from memory_pages import (_base_effects, _page_effect, _path_effect, available,
                          exact, field_record, finish_plan, index_patch, managed_path, ownership, page,
                          update_fields, writer)

COMMANDS = {"adopt-page": "adopt", "review-adoption": "review_adoption",
            "rename-page": "rename", "merge-pages": "merge", "retire-page": "retire",
            "forget-page": "delete", "resolve-memory-conflict": "resolve"}


def observed(row, expected_hash):
    data = read_bytes(target(row["path"]))
    if data is None or digest(data) != expected_hash:
        raise MemoryConflict("reviewed page bytes changed; review the current snapshot")
    return data


def backlinks(conn, paths, plans, operation_id):
    """Every incoming link needs an explicit, hash-bound reconciliation plan."""
    found = set()
    root = workspace() / "memory"
    for candidate in root.rglob("*.md"):
        relative = str(candidate.relative_to(root))
        if relative in paths or relative in {"index.md", "log.md"}:
            continue
        data = read_bytes(target(relative))
        for link in re.findall(rb"\]\(([^)\s]+)\)", data or b""):
            normalized = posixpath.normpath(posixpath.join(posixpath.dirname(relative), link.decode()))
            if normalized in paths:
                found.add(relative)
        # Reference-style links cannot be classified by this small planner.
        if any(path.encode() in (data or b"") for path in paths) and relative not in found:
            raise MemoryConflict("ambiguous backlink requires a separate reviewed repair")
    files, records, page_rows = [], [], []
    supplied = set()
    for plan in plans:
        exact(plan, {"path", "expected_hash"}, {"fields", "text"})
        if plan["path"] not in found:
            raise MemoryConflict("backlink plan includes an unrelated page")
        supplied.add(plan["path"])
        row = conn.execute("SELECT * FROM pages WHERE path=? AND state='active'", (plan["path"],)).fetchone()
        if row:
            if "fields" not in plan or "text" in plan:
                raise MemoryConflict("managed backlinks require field changes")
            file, fields = update_fields(conn, dict(row), plan, operation_id)
            files.append(file)
            records.extend(fields)
            page_rows.append(dict(row))
        else:
            if "text" not in plan or "fields" in plan or not isinstance(plan["text"], str):
                raise MemoryConflict("unmanaged backlink requires an explicitly reviewed complete file")
            before = read_bytes(target(plan["path"]))
            if digest(before) != plan["expected_hash"]:
                raise MemoryConflict("backlink precondition changed")
            files.append((plan["path"], before, plan["text"].encode()))
    if found != supplied:
        raise MemoryConflict("backlink plan does not cover every referring page")
    return files, records, page_rows


def declared_sidecars(conn, row):
    if row["path"].split("/")[0] != "projects":
        return []
    names = set()
    for record in conn.execute("SELECT effects_json FROM page_operations WHERE status='complete'"):
        effect = json.loads(record[0])["effects"]
        names.update(effect.get("sidecars", {}).get(row["page_id"], []))
    folder = target(row["path"]).parent
    allowed = {PurePosixPath(row["path"]).name} | names
    for child in folder.iterdir():
        if child.name not in allowed:
            raise MemoryConflict("project has an undeclared sidecar; review its ownership first")
        read_bytes(child)
    return [str(PurePosixPath(row["path"]).parent / name) for name in sorted(names)]


def compile_user(conn, action, request, operation_id):
    common = {"request_id", "store_instance_id"}
    effects, files, index, reservations = _base_effects(), [], [], []
    if action == "adopt":
        exact(request, common | {"path", "expected_hash", "fields"}, {"sidecars"})
        kind = managed_path(request["path"])
        if conn.execute("SELECT 1 FROM page_paths WHERE path_key=?", (path_key(request["path"]),)).fetchone():
            raise MemoryConflict("page path already registered")
        before = read_bytes(target(request["path"]))
        if before is None or digest(before) != request["expected_hash"]:
            raise MemoryConflict("adoption requires the exact observed file")
        doc = Document(before)
        validate_scope(doc, request["fields"])
        if not request["fields"]:
            raise MemoryConflict("adoption scope must contain at least one field")
        row = {"page_id": str(uuid.uuid4()), "page_type": kind, "path": request["path"],
               "path_key": path_key(request["path"]), "state": "active"}
        reservations.append(row)
        files.append((row["path"], before, before))
        effects["pages"].append(_page_effect(row))
        effects["paths"].append(_path_effect(row))
        effects["page_ids"].append(row["page_id"])
        for name, policy in request["fields"].items():
            record = field_record(row["page_id"], name, doc.field(name), operation_id, origin="adopted", policy=policy)
            effects["fields"].append(record)
            effects.setdefault("resolutions", []).append({"page_id": row["page_id"], "field_path": name,
                                                           "hash": record["last_content_hash"]})
        if request.get("sidecars"):
            if kind != "projects" or set(request["sidecars"]) - {"log.md", "log.archive.md"}:
                raise MemoryConflict("undeclared sidecar type")
            effects["sidecars"] = {row["page_id"]: list(request["sidecars"])}
            for name, expected in request["sidecars"].items():
                relative = str(PurePosixPath(row["path"]).parent / name)
                content = read_bytes(target(relative))
                if content is None or digest(content) != expected:
                    raise MemoryConflict("sidecar adoption precondition changed")
                files.append((relative, content, content))
        # Adoption captures ownership without modifying the page or its index.
    elif action == "review_adoption":
        exact(request, common | {"page_id", "expected_hash", "fields"})
        row = page(conn, request["page_id"])
        before = observed(row, request["expected_hash"])
        doc = Document(before)
        files.append((row["path"], before, before))
        effects["page_ids"].append(row["page_id"])
        for name, expected in request["fields"].items():
            field = conn.execute("SELECT * FROM managed_fields WHERE page_id=? AND field_path=?", (row["page_id"], name)).fetchone()
            if not field or field["content_origin"] != "adopted" or not field["awaiting_first_review"]:
                raise MemoryConflict("field is not awaiting adoption review")
            if expected != field["last_content_hash"] or digest(doc.field(name)) != expected:
                raise MemoryConflict("review is not for the originally observed field")
            # Validate the ownership receipt even though first review is still
            # pending. Neither an arbitrary user event nor a FK is authority.
            owner = conn.execute("SELECT * FROM page_operations WHERE operation_id=?", (field["ownership_operation_id"],)).fetchone()
            if not owner or owner["actor"] != "user" or owner["op_type"] != "adopt" or owner["status"] != "complete":
                raise MemoryConflict("field lacks a completed adoption operation")
            effects.setdefault("reviews", []).append({"page_id": row["page_id"], "field_path": name, "hash": expected})
            for resolution in conn.execute("SELECT * FROM pending_resolutions WHERE page_id=? AND resolution_type='adoption_review' AND status='pending'", (row["page_id"],)):
                if json.loads(resolution["payload_json"]).get("field_path") == name:
                    effects.setdefault("resolved", []).append({"id": resolution["resolution_id"], "choice": "accept",
                                                               "digest": journal.json_digest({name: expected})})
    else:
        required = common | {"page_id", "expected_hash"}
        optional = {"backlinks", "sidecars"}
        if action == "rename":
            required |= {"to"}
        elif action == "merge":
            required |= {"source_id", "source_hash", "fields"}
        exact(request, required, optional)
        row = page(conn, request["page_id"])
        before = observed(row, request["expected_hash"])
        effects["page_ids"].append(row["page_id"])
        if action in {"rename", "delete"}:
            owned = declared_sidecars(conn, row)
            provided = request.get("sidecars", {})
            if set(provided) != set(owned):
                raise MemoryConflict("operation must review every declared sidecar")
            for relative in owned:
                if digest(read_bytes(target(relative))) != provided[relative]:
                    raise MemoryConflict("sidecar precondition changed")
            linked_files, fields, rows = backlinks(conn, {row["path"]}, request.get("backlinks", []), operation_id)
            files.extend(linked_files)
            effects["fields"].extend(fields)
            effects["pages"].extend(_page_effect(r) for r in rows)
            effects["page_ids"].extend(r["page_id"] for r in rows)
            # A reviewed patch must actually remove the old reference.
            for name, _, after in linked_files:
                for link in re.findall(rb"\]\(([^)\s]+)\)", after):
                    if posixpath.normpath(posixpath.join(posixpath.dirname(name), link.decode())) == row["path"]:
                        raise MemoryConflict("backlink plan leaves an old-path reference")
        if action == "rename":
            new = request["to"]
            if managed_path(new, generated=True) != row["path"].split("/")[0]:
                raise MemoryConflict("rename cannot change page type")
            case_only = path_key(new) == row["path_key"] and new != row["path"]
            if case_only:
                # The temporary resource is recorded twice with distinct step
                # keys: absent -> bytes, then bytes -> absent. Recovery skips
                # acknowledged stages and verifies the final state per path.
                temp = str(PurePosixPath(row["path"]).parent /
                           ("_memory_stage_" + operation_id.replace("-", "") + ".md"))
                if row["page_type"] == "projects":
                    temp = "projects/_memory_stage_" + operation_id.replace("-", "") + ".md"
                available(conn, temp)
                if target(new).exists() and not target(new).samefile(target(row["path"])):
                    raise MemoryConflict("case-only destination contains another file")
                files.extend([(temp, None, before), (row["path"], before, None),
                              (new, None, before), (temp, before, None)])
                effects["staged_rename"] = True
            else:
                available(conn, new)
                files.extend([(new, None, before), (row["path"], before, None)])
            for relative in owned:
                dest = str(PurePosixPath(new).parent / PurePosixPath(relative).name)
                if not case_only:
                    available(conn, dest)
                content = read_bytes(target(relative))
                if case_only:
                    temp = "projects/_memory_stage_" + uuid.uuid4().hex + ".md"
                    available(conn, temp)
                    files.extend([(temp, None, content), (relative, content, None),
                                  (dest, None, content), (temp, content, None)])
                else:
                    files.extend([(dest, None, content), (relative, content, None)])
            updated = _page_effect(row, path=new, path_key=path_key(new))
            if not case_only:
                effects["paths"].append(_path_effect(row, "alias"))
            effects["paths"].append(_path_effect(updated))
            effects["pages"].append(updated)
            index.append({"path": row["path"], "mode": "rename", "to": new})
        elif action in {"retire", "merge"}:
            retiring = row
            retiring_before = before
            if action == "merge":
                source = page(conn, request["source_id"])
                if source["page_id"] == row["page_id"] or source["state"] != "active":
                    raise MemoryConflict("merge needs a distinct active source")
                if source["page_type"] != row["page_type"]:
                    raise MemoryConflict("merge requires matching page types")
                retiring_before = observed(source, request["source_hash"])
                file, fields = update_fields(conn, row, request, operation_id)
                files.append(file)
                effects["fields"].extend(fields)
                effects["pages"].append(_page_effect(row))
                effects["page_ids"].append(source["page_id"])
                retiring = source
                effects["merge"] = {"survivor": row["page_id"], "source": source["page_id"]}
            files.append((retiring["path"], retiring_before, retiring_before))
            effects["pages"].append(_page_effect(retiring, state="retired"))
            index.append({"path": retiring["path"], "mode": "retire"})
        elif action == "delete":
            files.append((row["path"], before, None))
            for relative in owned:
                files.append((relative, read_bytes(target(relative)), None))
            effects["pages"].append(_page_effect(row, state="deleted", path=None, path_key=None))
            for old in conn.execute("SELECT * FROM page_paths WHERE page_id=?", (row["page_id"],)):
                effects["paths"].append(_path_effect(dict(old), "tombstone"))
            effects["forget"] = [row["page_id"]]
            index.append({"path": row["path"], "mode": "remove"})
        else:
            raise MemoryConflict("unsupported user action")
    return (*finish_plan(files, effects, index, operation_id, action), reservations)


def apply_user(command, request, *, fault=None):
    if command not in COMMANDS:
        raise MemoryConflict("unknown page command")
    action = COMMANDS[command]
    if action == "resolve":
        return resolve(request, fault=fault)
    request_hash = journal.json_digest({"action": action, "request": request})
    with writer(check_skills=False):
        prior = journal.lookup_request(request["request_id"], request_hash)
        if prior:
            return journal.result_for(prior)
        op = str(uuid.uuid4())
        with journal.connection() as conn:
            files, effects, reservations = compile_user(conn, action, request, op)
        journal.prepare(operation_id=op, request_id=request["request_id"], request_digest=request_hash,
                        instance=request["store_instance_id"], op_type=action, actor="user", files=files,
                        effects=effects, reservations=reservations)
        if fault:
            fault("prepared", None)
        result = journal.recover_locked(fault=fault)
        result["page_ids"] = effects["page_ids"]
        return result


def resolve(request, *, fault=None):
    exact(request, {"request_id", "store_instance_id", "operation_id", "choice", "observed"}, {"replacement"})
    with writer(check_skills=False, recover=False):
        prior = journal.lookup_request(request["request_id"], journal.json_digest(request))
        if prior:
            choice = json.loads(prior["effects_json"])["effects"].get("resolution", {}).get("choice")
            if choice == "cancel":
                return {"status": "cancelled", "operation_id": request["operation_id"]}
            if choice == "retry":
                result = journal.recover_locked(fault=fault)
                if result["status"] != "clean":
                    return result
                with journal.connection() as conn:
                    original = conn.execute("SELECT * FROM page_operations WHERE operation_id=?", (request["operation_id"],)).fetchone()
                    return journal.result_for(original)
            return {"status": prior["status"], "operation_id": prior["operation_id"]}
        with journal.connection() as conn:
            if request["store_instance_id"] != journal.store_id(conn):
                raise MemoryConflict("resolution belongs to an old store")
            op = conn.execute("SELECT * FROM page_operations WHERE operation_id=?", (request["operation_id"],)).fetchone()
            if not op or op["status"] not in {"prepared", "applying", "blocked_diverged"}:
                raise MemoryConflict("operation is not awaiting resolution")
            steps = [dict(r) for r in conn.execute("SELECT * FROM memory_steps WHERE operation_id=? AND target_path IS NOT NULL", (op["operation_id"],))]
            reservations = [dict(r) for r in conn.execute("SELECT p.* FROM pages p JOIN operation_pages o USING(page_id) WHERE o.operation_id=? AND p.state='reserved'", (op["operation_id"],))]
            affected_pages = [dict(r) for r in conn.execute("SELECT p.* FROM pages p JOIN operation_pages o USING(page_id) WHERE o.operation_id=?", (op["operation_id"],))]
        actual = {step["target_path"]: read_bytes(target(step["target_path"])) for step in steps}
        if request["observed"] != {name: digest(data) for name, data in actual.items()}:
            raise MemoryConflict("resolution must review every actual affected path")
        choice = request["choice"]
        if choice == "cancel":
            if op["status"] != "prepared" or any(step["status"] == "applied" and step["before_hash"] != step["after_hash"] or
                   digest(actual[step["target_path"]]) != step["before_hash"] for step in steps):
                raise MemoryConflict("operation is not provably before file effects; use a compensating replacement")
            with write_txn() as conn:
                conn.execute("UPDATE page_operations SET status='cancelled',completed_at=? WHERE operation_id=?", (journal.stamp(), op["operation_id"]))
                for row in reservations:
                    conn.execute("UPDATE pages SET state='deleted',path=NULL,path_key=NULL WHERE page_id=?", (row["page_id"],))
                    conn.execute("DELETE FROM page_paths WHERE page_id=? AND disposition='reserved'", (row["page_id"],))
                journal.scrub(conn, op["operation_id"])
                conn.execute("UPDATE pending_resolutions SET status='resolved',choice='cancel',payload_json='{}',decision_digest=?,resolved_at=? WHERE operation_id=? AND status='pending'",
                             (journal.json_digest(request), journal.stamp(), op["operation_id"]))
                audit_resolution(conn, request)
            return {"status": "cancelled", "operation_id": op["operation_id"]}
        if choice == "retry":
            if any(step["payload_cleared_at"] or digest(actual[step["target_path"]]) not in {step["before_hash"], step["after_hash"]} for step in steps):
                raise MemoryConflict("retry requires retained payload and reviewed before/after images")
            with write_txn() as conn:
                conn.execute("UPDATE page_operations SET status='prepared' WHERE operation_id=?", (op["operation_id"],))
                conn.execute("UPDATE pending_resolutions SET status='resolved',choice='retry',payload_json='{}',decision_digest=?,resolved_at=? WHERE operation_id=? AND status='pending'",
                             (journal.json_digest(request), journal.stamp(), op["operation_id"]))
                audit_resolution(conn, request)
            return journal.recover_locked(fault=fault)
        if choice != "replace":
            raise MemoryConflict("resolution choice must be cancel, retry, or replace")
        # Compensate from every actual path. Previously existing canonical
        # files must remain present so the old registry remains usable. The
        # user can retain new files as unmanaged content; preserving
        # bytes does not create generated ownership or a completed claim.
        replacements = request.get("replacement", {})
        if set(replacements) != set(actual):
            raise MemoryConflict("replacement must cover every affected path")
        first_steps = {}
        for step in steps:
            first_steps.setdefault(step["target_path"], step)
        final = {}
        for step in first_steps.values():
            name = step["target_path"]
            text = replacements[name]
            after = None if text is None else text.encode()
            if after is None and step["before_presence"] == "present":
                raise MemoryConflict("compensation must restore previously existing paths")
            if PurePosixPath(name).name.startswith("_memory_stage_") and after is not None:
                raise MemoryConflict("reserved staging paths must be removed")
            final[name] = after
        effects = _base_effects()
        effects["page_ids"] = [row["page_id"] for row in affected_pages]
        for row in reservations:
            effects["pages"].append(_page_effect(row, state="deleted", path=None, path_key=None))
            effects.setdefault("release_reservations", []).append(row["page_id"])
        with journal.connection() as conn:
            for row in affected_pages:
                if row["state"] == "reserved":
                    continue
                data = final.get(row["path"])
                if data is None:
                    raise MemoryConflict("compensation must retain the registered canonical page")
                doc = Document(data)
                effects["pages"].append(_page_effect(row))
                for item in conn.execute("SELECT * FROM managed_fields WHERE page_id=?", (row["page_id"],)):
                    field = dict(item)
                    if field["awaiting_first_review"]:
                        continue
                    ownership(conn, field)
                    content_hash = digest(doc.field(field["field_path"]))
                    if field["ownership_policy"] != "cas_protected" and content_hash != field["last_content_hash"]:
                        raise MemoryConflict("compensation cannot rewrite immutable fields or entry IDs")
                    field["last_content_hash"] = content_hash
                    field["last_evidence_digest"] = None
                    effects["fields"].append(field)
        effects["resolution"] = {"operation_id": op["operation_id"], "decision_digest": journal.json_digest(request)}
        replacement_id = str(uuid.uuid4())
        files = compensation_files(final, actual, effects, replacement_id)
        if op["status"] != "blocked_diverged":
            journal.block(op["operation_id"])
        journal.prepare(operation_id=replacement_id, request_id=request["request_id"], request_digest=journal.json_digest(request),
                        instance=request["store_instance_id"], op_type="resolve", actor="user", files=files, effects=effects,
                        supersedes=op["operation_id"])
        return journal.recover_locked(fault=fault)


def compensation_files(final, actual, effects, operation_id):
    """Compile reviewed final images, including case-only restoration stages."""
    groups = {}
    for name in final:
        groups.setdefault(path_key(name), []).append(name)
    files, deletions = [], []
    for names in groups.values():
        if set(names) & {"index.md", "log.md"}:
            continue
        if len(names) == 1:
            name = names[0]
            (deletions if final[name] is None else files).append((name, actual[name], final[name]))
            continue
        keep = [name for name in names if final[name] is not None]
        if len(keep) != 1:
            raise MemoryConflict("case-equivalent paths require one reviewed canonical destination")
        destination = keep[0]
        temp = destination.split("/")[0] + "/_memory_stage_" + uuid.uuid4().hex + ".md"
        if read_bytes(target(temp)) is not None:
            raise MemoryConflict("compensation staging path already exists")
        files.append((temp, None, final[destination]))
        seen = set()
        for name in names:
            if actual[name] is None:
                continue
            info = target(name).stat()
            inode = (info.st_dev, info.st_ino)
            if inode in seen:
                continue
            if seen:
                raise MemoryConflict("case-equivalent paths contain distinct live files")
            seen.add(inode)
            files.append((name, actual[name], None))
        files.extend([(destination, None, final[destination]), (temp, final[destination], None)])
        effects["staged_rename"] = True
    # Reconcile only the affected page entries. The user-chosen text remains
    # intact; the deterministic index and operation marker follow final paths.
    index_before = read_bytes(target("index.md"))
    index_after = final.get("index.md", index_before)
    changes = []
    for name, data in final.items():
        leaf = PurePosixPath(name).name
        if name in {"index.md", "log.md"} or leaf.startswith("_memory_stage_") or leaf in {"log.md", "log.archive.md"}:
            continue
        changes.append({"path": name, "mode": "remove" if data is None else "add"})
    if changes:
        # Remove first so case-only restoration cannot retain an alias entry.
        changes.sort(key=lambda change: change["mode"] != "remove")
        index_after = index_patch(index_after, changes)
    if index_after != index_before:
        files.append(("index.md", index_before, index_after))
    log_before = read_bytes(target("log.md"))
    log_after = final.get("log.md", log_before) or b"# Memory log\n"
    log_after += f"\n- {journal.stamp()} resolve <!-- mdcos:operation:{operation_id} -->\n".encode()
    files.append(("log.md", log_before, log_after))
    return files + deletions


def audit_resolution(conn, request):
    """Record explicit cancellation/retry authority in the same transaction."""
    operation_id = str(uuid.uuid4())
    now = journal.stamp()
    effects = {"resolution": {"operation_id": request["operation_id"], "choice": request["choice"],
                              "decision_digest": journal.json_digest(request)}}
    manifest = {"effects": effects, "files": [], "actor": "user", "type": "resolve",
                "instance": request["store_instance_id"], "reservations": []}
    conn.execute("INSERT INTO page_operations(operation_id,request_id,request_digest,store_instance_id,op_type,actor,"
                 "status,effects_json,plan_digest,created_at,completed_at) VALUES (?,?,?,?,'resolve','user','complete',?,?,?,?)",
                 (operation_id, request["request_id"], journal.json_digest(request), request["store_instance_id"],
                  journal.canonical(manifest), journal.json_digest(manifest), now, now))
    conn.execute("INSERT INTO page_events VALUES (?,?,'user','resolve',?,?)",
                 (str(uuid.uuid4()), operation_id, journal.canonical(effects["resolution"]), now))
