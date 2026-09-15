# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Foundation acceptance using real SQLite, files, subprocesses, and fault points."""

from __future__ import annotations

import base64
import copy
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

from _db import ensure_store, write_txn
from memory_corrections import apply_user
from memory_fields import Document
from memory_io import MemoryBlocked, MemoryConflict, digest, memory_lock, read_snapshot
import memory_journal as journal
from memory_operations import check, recover, set_enabled, snapshot
from memory_pages import apply

TEXT = b"---\nname: Example\n---\n\n## Definition\nA useful concept.\n"
FIELDS = ["frontmatter:name", "section:Definition"]


class Interrupted(BaseException):
    pass


class FoundationCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="foundation-test-")
        self.home = Path(self.temp.name).resolve()
        self.env = patch.dict(os.environ, {"HERMES_HOME": str(self.home)})
        self.env.start()
        shutil.copytree(HERE.parent / "skills", self.home / "skills")
        self.db = ensure_store()
        set_enabled(True)
        self.instance = check()["store_instance_id"]
        self.root = self.home / "workspace/memory"
        self.addCleanup(self.env.stop)
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(journal.COMPLETION_HANDLERS.clear)
        from memory_io import READ_GUARDS
        self.addCleanup(READ_GUARDS.clear)

    def proposal(self, action="create", **extra):
        return {"version": 1, "request_id": str(uuid.uuid4()), "store_instance_id": self.instance,
                "action": action, **extra}

    def creation(self, path="concepts/example.md", text=TEXT, **extra):
        return self.proposal(changes=[{"path": path, "text": text.decode(), "fields": FIELDS, **extra}])

    def create(self, **kwargs):
        return apply(self.creation(**kwargs))["page_ids"][0]

    def user(self, command, **extra):
        return apply_user(command, {"request_id": str(uuid.uuid4()), "store_instance_id": self.instance, **extra})

    def rows(self, table):
        with journal.connection() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM " + table)]

    def update(self, page_id, text="## Definition\nA revised concept.\n", path="concepts/example.md", **extra):
        return apply(self.proposal("update", changes=[{"page_id": page_id,
                     "expected_hash": digest((self.root / path).read_bytes()),
                     "fields": {"section:Definition": text}, **extra}]))

    @staticmethod
    def interrupt_at(where, ordinal=None):
        def stop(point, index):
            if point == where and index == ordinal:
                raise Interrupted()
        return stop

    def test_migration_does_not_adopt_existing_content(self):
        self.assertTrue((HERE / "schema.sql").read_text().endswith((HERE / "schema-memory.sql").read_text()))
        before = self.instance
        ensure_store()
        self.assertEqual(check()["store_instance_id"], before)
        self.assertEqual(self.rows("pages"), [])
        legacy = self.home / "old.db"
        with sqlite3.connect(legacy) as conn:
            conn.executescript((HERE / "schema-v6.sql").read_text())
            conn.execute("INSERT INTO items(source_id,source,scope,event_at,body,state) VALUES ('one','email','inbox','2026-01-01','original','pending')")
            from migrate import migrate
            self.assertEqual(migrate(conn), [7])
            self.assertEqual(conn.execute("SELECT body FROM items").fetchone()[0], "original")
            self.assertEqual(conn.execute("SELECT count(*) FROM pages").fetchone()[0], 0)
            identity = journal.store_id(conn)
            self.assertEqual(migrate(conn), [])
            self.assertEqual(journal.store_id(conn), identity)

    def test_generated_content_refreshes_without_adoption(self):
        page_id = self.create()
        from memory_check import check_index
        self.assertEqual(check_index(self.root), [])
        self.update(page_id)
        self.assertIn(b"revised", (self.root / "concepts/example.md").read_bytes())
        fields = self.rows("managed_fields")
        self.assertTrue(all(f["content_origin"] == "generated" and not f["awaiting_first_review"] for f in fields))
        self.assertEqual(self.rows("pending_resolutions"), [])
        self.assertTrue(all(s["before_bytes"] is None and s["after_bytes"] is None for s in self.rows("memory_steps")))

    def test_existing_file_collision_prepares_nothing(self):
        path = self.root / "concepts/example.md"
        path.parent.mkdir(parents=True)
        path.write_bytes(TEXT)
        with self.assertRaises(MemoryConflict):
            self.create()
        self.assertEqual(path.read_bytes(), TEXT)
        self.assertEqual(self.rows("pages"), [])
        self.assertEqual(self.rows("page_operations"), [])
        self.create(path="concepts/unrelated.md")

    def test_model_cannot_select_actor_or_origin(self):
        for key in ("actor", "content_origin", "effects", "sql", "review_operation_id"):
            proposal = self.creation()
            proposal[key] = "user"
            with self.subTest(key=key), self.assertRaises(MemoryConflict):
                apply(proposal)
        for action in ("adopt", "delete", "resolve", "rename", "review_adoption"):
            with self.subTest(action=action), self.assertRaises(MemoryConflict):
                apply(self.proposal(action))
        self.assertEqual(self.rows("page_operations"), [])

    def test_partial_generated_ownership_preserves_handwritten_bytes(self):
        text = b"---\n# keep comment\nname: Example\n---\n\n## Definition\nOld.\n\n## Private notes\nHandwritten  \n"
        page_id = self.create(text=text)
        tail = text[text.index(b"## Private"):]
        self.update(page_id)
        self.assertTrue((self.root / "concepts/example.md").read_bytes().endswith(tail))
        self.assertIn(b"# keep comment", (self.root / "concepts/example.md").read_bytes())
        with self.assertRaises(MemoryConflict):
            apply(self.proposal("update", changes=[{"page_id": page_id, "expected_hash": digest((self.root / "concepts/example.md").read_bytes()),
                                                   "fields": {"section:Private notes": "## Private notes\nOverwrite.\n"}}]))

    def test_external_edit_is_not_implicit_feedback(self):
        page_id = self.create()
        path = self.root / "concepts/example.md"
        changed = TEXT.replace(b"useful", b"handwritten")
        path.write_bytes(changed)
        with self.assertRaises(MemoryConflict):
            self.update(page_id)
        self.assertEqual(path.read_bytes(), changed)
        self.assertEqual(len(self.rows("page_operations")), 1)
        self.assertEqual(self.rows("pending_resolutions"), [])

    def test_adoption_requires_hash_specific_user_review(self):
        path = self.root / "concepts/example.md"
        path.parent.mkdir(parents=True)
        path.write_bytes(TEXT)
        page_id = self.user("adopt-page", path="concepts/example.md", expected_hash=digest(TEXT), fields={"section:Definition": "cas_protected"})["page_ids"][0]
        self.assertEqual(path.read_bytes(), TEXT)
        with self.assertRaises(MemoryConflict):
            self.update(page_id)
        self.user("review-adoption", page_id=page_id, expected_hash=digest(TEXT), fields={"section:Definition": digest(Document(TEXT).field("section:Definition"))})
        self.update(page_id)
        self.assertEqual([r["actor"] for r in self.rows("page_events")], ["user", "user", "agent"])
        self.assertEqual(self.rows("events"), [])

    def test_modified_adoption_does_not_clear_review_flag(self):
        path = self.root / "concepts/example.md"
        path.parent.mkdir(parents=True)
        path.write_bytes(TEXT)
        page_id = self.user("adopt-page", path="concepts/example.md", expected_hash=digest(TEXT), fields={"section:Definition": "cas_protected"})["page_ids"][0]
        path.write_bytes(TEXT.replace(b"useful", b"changed"))
        with self.assertRaises(MemoryConflict):
            self.user("review-adoption", page_id=page_id, expected_hash=digest(path.read_bytes()), fields={"section:Definition": digest(Document(path.read_bytes()).field("section:Definition"))})
        self.assertEqual(self.rows("managed_fields")[0]["awaiting_first_review"], 1)

    def test_sql_foreign_key_is_not_ownership_authority(self):
        page_id = self.create()
        apply(self.proposal("log_only"))
        other = self.rows("page_operations")[-1]["operation_id"]
        with write_txn() as conn:
            conn.execute("UPDATE managed_fields SET ownership_operation_id=?", (other,))
        with self.assertRaises(MemoryConflict):
            self.update(page_id)

    def test_new_absent_field_is_automatically_owned(self):
        page_id = self.create()
        result = apply(self.proposal("update", changes=[{"page_id": page_id, "expected_hash": digest(TEXT),
                  "fields": {"section:Examples": "## Examples\nOne example.\n"}}]))
        self.assertEqual(result["status"], "complete")
        self.assertEqual(len(self.rows("managed_fields")), 3)

    def test_additive_entry_cannot_be_rewritten(self):
        page_id = self.create()
        # Add a sibling section first so the entry does not overlap an owned
        # section extending to EOF. Its container is deliberately unmanaged.
        path = self.root / "concepts/example.md"
        path.write_bytes(TEXT + b"\n## Notes\n")
        entry = "<!-- mdcos:entry:one -->\nA note.\n<!-- /mdcos:entry:one -->\n"
        def envelope(content):
            return self.proposal("update", changes=[{"page_id": page_id, "expected_hash": digest(path.read_bytes()), "fields": {"entry:one": content}}])
        apply(envelope(entry))
        apply(envelope(entry))
        with self.assertRaises(MemoryConflict):
            apply(envelope(entry.replace("A note.", "Changed.")))

    def test_ambiguous_documents_are_rejected(self):
        for text in (b"---\nname: one\nname: two\n---\n", b"## Same\nOne\n## Same\nTwo\n",
                     b"<!-- mdcos:entry:one -->\n", b"<!-- /mdcos:entry:one -->\n",
                     b"<!-- mdcos:entry:one -->\n<!-- mdcos:entry:two -->\n",
                     b"---\nmap:\n  key: one\n  key: two\n---\n"):
            with self.subTest(text=text), self.assertRaises(MemoryConflict):
                Document(text)

    def test_faults_recover_each_resource_once(self):
        points = [("prepared", None), ("registry", None), ("audit", None), ("completion", None)]
        points += [(point, ordinal) for point in ("before_file", "after_file") for ordinal in range(3)]
        for n, (point, ordinal) in enumerate(points):
            with self.subTest(point=point, ordinal=ordinal):
                proposal = self.creation(path=f"concepts/example_{n}.md")
                with self.assertRaises(Interrupted):
                    apply(proposal, fault=self.interrupt_at(point, ordinal))
                with self.assertRaises(MemoryBlocked):
                    snapshot(["index.md"])
                result = recover()
                self.assertEqual(result["status"], "complete")
                retry = apply(proposal)
                self.assertEqual(retry["operation_id"], result["operation_id"])
                self.assertEqual((self.root / "log.md").read_text().count(result["operation_id"]), 1)
                self.assertEqual((self.root / f"concepts/example_{n}.md").read_bytes(), TEXT)
        self.assertEqual(len(self.rows("page_events")), len(points))

    def test_request_digest_mismatch_is_rejected(self):
        proposal = self.creation()
        apply(proposal)
        proposal["changes"][0]["text"] += "\n"
        with self.assertRaises(MemoryConflict):
            apply(proposal)

    def test_divergence_blocks_without_overwriting(self):
        proposal = self.creation()
        with self.assertRaises(Interrupted):
            apply(proposal, fault=self.interrupt_at("after_file", 0))
        path = self.root / "concepts/example.md"
        path.write_bytes(b"Handwritten during interruption.\n")
        with self.assertRaises(MemoryBlocked):
            recover()
        self.assertEqual(check()["status"], "blocked_diverged")
        self.assertEqual(path.read_bytes(), b"Handwritten during interruption.\n")
        with self.assertRaises(MemoryBlocked):
            apply(self.creation(path="concepts/other.md"))

    def test_cancel_only_before_persistent_effects(self):
        with self.assertRaises(Interrupted):
            apply(self.creation(), fault=self.interrupt_at("prepared"))
        status = check()
        set_enabled(False)
        self.assertEqual(check()["status"], "prepared")
        self.assertFalse(check()["enabled"])
        request = {"operation_id": status["operation_id"], "choice": "cancel", "observed": {
            s["target_path"]: None for s in self.rows("memory_steps") if s["target_path"]}}
        result = self.user("resolve-memory-conflict", **request)
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(check()["status"], "clean")
        self.assertTrue(all(r["after_bytes"] is None for r in self.rows("memory_steps")))
        self.assertEqual(self.rows("page_paths"), [])
        set_enabled(True)
        self.create()

    def test_unknown_completion_handler_refuses_preparation(self):
        with self.assertRaises(MemoryBlocked):
            apply(self.creation(), completion=[{"handler": "test.complete.v1"}])
        self.assertEqual(self.rows("page_operations"), [])
        self.assertFalse((self.root / "concepts/example.md").exists())

    def test_completion_failure_rolls_back_registry_and_receipt(self):
        with write_txn() as conn:
            conn.execute("CREATE TABLE test_receipts(operation_id TEXT PRIMARY KEY)")
        fail = [True]
        def complete(conn, effect, operation):
            conn.execute("INSERT INTO test_receipts VALUES (?)", (operation["operation_id"],))
            if fail[0]:
                raise RuntimeError("injected completion failure")
        journal.register_completion("test.complete.v1", required_tables=["test_receipts"], validate=lambda *a: None, apply=complete)
        with self.assertRaises(RuntimeError):
            apply(self.creation(), completion=[{"handler": "test.complete.v1"}])
        self.assertEqual(self.rows("page_events"), [])
        self.assertEqual(self.rows("managed_fields"), [])
        self.assertEqual(self.rows("test_receipts"), [])
        self.assertEqual((self.root / "concepts/example.md").read_bytes(), TEXT)
        fail[0] = False
        recover()
        self.assertEqual(len(self.rows("test_receipts")), 1)
        self.assertEqual(recover()["status"], "clean")

    def test_completion_extension_requires_its_migration(self):
        journal.register_completion("test.complete.v1", required_tables=["absent_table"], validate=lambda *a: None, apply=lambda *a: None)
        with self.assertRaises(MemoryBlocked):
            apply(self.creation(), completion=[{"handler": "test.complete.v1"}])
        self.assertEqual(self.rows("page_operations"), [])

    def test_unknown_recovery_handler_keeps_reader_gate(self):
        journal.register_completion("test.complete.v1", required_tables=[], validate=lambda *a: None, apply=lambda *a: None)
        with self.assertRaises(Interrupted):
            apply(self.creation(), completion=[{"handler": "test.complete.v1"}], fault=self.interrupt_at("prepared"))
        saved = journal.COMPLETION_HANDLERS.pop("test.complete.v1")
        with self.assertRaises(MemoryBlocked):
            recover()
        with self.assertRaises(MemoryBlocked):
            snapshot(["index.md"])
        journal.COMPLETION_HANDLERS["test.complete.v1"] = saved
        recover()

    def test_disable_preserves_transport_for_legacy_pages(self):
        self.create()
        set_enabled(False)
        with self.assertRaises(MemoryBlocked):
            self.create(path="concepts/disabled.md")
        apply(self.proposal("legacy_write", changes=[{"path": "people/example.md", "expected_hash": None,
                 "text": "---\nname: Example\noutbound_evidence: sha256:batch:11\n---\nEvidence.\n"}],
                 index=[{"path": "people/example.md", "mode": "add"}]))
        self.assertIn("sha256:batch:11", (self.root / "people/example.md").read_text())
        self.assertEqual(len(self.rows("pages")), 1)

    def test_incompatible_effective_skill_blocks_activation_and_writes(self):
        path = self.home / "skills/memory-repair/SKILL.md"
        original = path.read_bytes()
        path.write_bytes(original.replace(b"memory-operation-protocol: 1", b"memory-operation-protocol: 0"))
        with self.assertRaises(MemoryBlocked):
            set_enabled(True)
        with self.assertRaises(MemoryBlocked):
            apply(self.proposal("log_only"))
        self.assertEqual(path.read_bytes(), original.replace(b"memory-operation-protocol: 1", b"memory-operation-protocol: 0"))

    def test_path_and_size_bounds_precede_preparation(self):
        for path in ("../outside.md", "/tmp/outside.md", "concepts/../outside.md", "goals/example.md", "concepts/Bad-Name.md"):
            with self.subTest(path=path), self.assertRaises(MemoryConflict):
                self.create(path=path)
        large = self.creation(text=TEXT + b"x" * (8 * 1024 * 1024))
        with self.assertRaises(MemoryConflict):
            apply(large)
        many = self.creation()
        many["changes"] = [{"path": f"concepts/example_{i}.md", "text": TEXT.decode(), "fields": FIELDS} for i in range(33)]
        with self.assertRaises(MemoryConflict):
            apply(many)
        self.assertEqual(self.rows("page_operations"), [])

    def test_symlink_and_hardlink_are_refused(self):
        outside = self.home / "outside.md"
        outside.write_bytes(TEXT)
        path = self.root / "concepts/example.md"
        path.parent.mkdir(parents=True)
        path.symlink_to(outside)
        with self.assertRaises(MemoryConflict):
            self.create()
        path.unlink()
        os.link(outside, path)
        with self.assertRaises(MemoryConflict):
            self.create()
        self.assertEqual(outside.read_bytes(), TEXT)

    def test_rename_retire_forget_preserve_stable_identity(self):
        page_id = self.create()
        self.user("rename-page", page_id=page_id, expected_hash=digest(TEXT), to="concepts/renamed.md")
        self.assertFalse((self.root / "concepts/example.md").exists())
        self.assertEqual(self.rows("pages")[0]["page_id"], page_id)
        self.assertEqual({r["disposition"] for r in self.rows("page_paths")}, {"alias", "canonical"})
        alias = snapshot(["concepts/example.md"])["files"]["concepts/example.md"]
        self.assertEqual(alias["canonical_path"], "concepts/renamed.md")
        self.assertEqual(alias["text"], TEXT.decode())
        self.user("retire-page", page_id=page_id, expected_hash=digest(TEXT))
        with self.assertRaises(MemoryConflict):
            self.update(page_id, path="concepts/renamed.md")
        self.user("forget-page", page_id=page_id, expected_hash=digest(TEXT))
        self.assertEqual(self.rows("pages")[0]["state"], "deleted")
        self.assertIsNone(self.rows("pages")[0]["path"])
        self.assertEqual(self.rows("managed_fields"), [])
        self.assertEqual({r["disposition"] for r in self.rows("page_paths")}, {"tombstone"})

    def test_merge_keeps_source_body_and_provenance(self):
        survivor = self.create()
        source = self.create(path="concepts/source.md")
        self.user("merge-pages", page_id=survivor, expected_hash=digest(TEXT), source_id=source,
                  source_hash=digest(TEXT), fields={"section:Definition": "## Definition\nReconciled concepts.\n"})
        self.assertEqual((self.root / "concepts/source.md").read_bytes(), TEXT)
        self.assertEqual({p["page_id"]: p["state"] for p in self.rows("pages")}, {survivor: "active", source: "retired"})
        self.assertEqual(len(self.rows("managed_fields")), 4)

    def test_unmanaged_backlink_requires_reviewed_patch(self):
        page_id = self.create()
        linked = self.root / "concepts/notes.md"
        linked.write_bytes(b"See [example](example.md).\n")
        with self.assertRaises(MemoryConflict):
            self.user("rename-page", page_id=page_id, expected_hash=digest(TEXT), to="concepts/renamed.md")
        self.user("rename-page", page_id=page_id, expected_hash=digest(TEXT), to="concepts/renamed.md",
                  backlinks=[{"path": "concepts/notes.md", "expected_hash": digest(linked.read_bytes()), "text": "See [example](renamed.md).\n"}])
        self.assertEqual(linked.read_bytes(), b"See [example](renamed.md).\n")

    def test_case_only_rename_uses_recorded_stages(self):
        old = self.root / "concepts/Example.md"
        old.parent.mkdir(parents=True)
        old.write_bytes(TEXT)
        page_id = self.user("adopt-page", path="concepts/Example.md", expected_hash=digest(TEXT), fields={"section:Definition": "cas_protected"})["page_ids"][0]
        apply(self.proposal("repair_index", index=[{"path": "concepts/Example.md", "mode": "add"}]))
        self.user("rename-page", page_id=page_id, expected_hash=digest(TEXT), to="concepts/example.md")
        self.assertEqual((self.root / "concepts/example.md").read_bytes(), TEXT)
        self.assertFalse(list(self.root.rglob("_memory_stage*")))
        self.assertEqual(self.rows("pages")[0]["path"], "concepts/example.md")
        for ordinal in range(4):
            with self.subTest(interrupted_stage=ordinal):
                original = f"concepts/Example_{ordinal}.md"
                destination = f"concepts/example_{ordinal}.md"
                (self.root / original).write_bytes(TEXT)
                page_id = self.user("adopt-page", path=original, expected_hash=digest(TEXT),
                                    fields={"section:Definition": "cas_protected"})["page_ids"][0]
                apply(self.proposal("repair_index", index=[{"path": original, "mode": "add"}]))
                request = {"request_id": str(uuid.uuid4()), "store_instance_id": self.instance,
                           "page_id": page_id, "expected_hash": digest(TEXT), "to": destination}
                with self.assertRaises(Interrupted):
                    apply_user("rename-page", request, fault=self.interrupt_at("after_file", ordinal))
                self.assertEqual(recover()["status"], "complete")
                self.assertEqual((self.root / destination).read_bytes(), TEXT)
                self.assertFalse(list(self.root.rglob("_memory_stage*")))
        original, destination = "concepts/Expired.md", "concepts/expired.md"
        (self.root / original).write_bytes(TEXT)
        page_id = self.user("adopt-page", path=original, expected_hash=digest(TEXT),
                            fields={"section:Definition": "cas_protected"})["page_ids"][0]
        apply(self.proposal("repair_index", index=[{"path": original, "mode": "add"}]))
        request = {"request_id": str(uuid.uuid4()), "store_instance_id": self.instance,
                   "page_id": page_id, "expected_hash": digest(TEXT), "to": destination}
        with self.assertRaises(Interrupted):
            apply_user("rename-page", request, fault=self.interrupt_at("after_file", 1))
        with write_txn() as conn:
            conn.execute("UPDATE page_operations SET created_at='2000-01-01T00:00:00+00:00' WHERE status='applying'")
        with self.assertRaises(MemoryBlocked):
            recover()
        from memory_operations import inspect_operation
        inspection = inspect_operation()
        selected = dict(inspection["files"])
        for path in selected:
            if Path(path).name.startswith("_memory_stage_"):
                selected[path] = None
        selected[original], selected[destination] = TEXT.decode(), None
        self.user("resolve-memory-conflict", operation_id=inspection["operation_id"], choice="replace",
                  observed=inspection["observed"], replacement=selected)
        self.assertEqual((self.root / original).read_bytes(), TEXT)
        self.assertFalse(list(self.root.rglob("_memory_stage*")))

    def test_project_logs_rotate_and_move_in_same_operation(self):
        path = "projects/example/example.md"
        page_id = self.create(path=path, sidecars={"log.md": {"expected_hash": None, "entries": {"one": "First event.", "two": "Second event."}}})
        log = self.root / "projects/example/log.md"
        proposal = self.proposal("update", changes=[{"page_id": page_id, "expected_hash": digest(TEXT), "fields": {},
                                 "sidecars": {"rotate": {"log_hash": digest(log.read_bytes()), "archive_hash": None, "entries": 1}}}])
        with self.assertRaises(Interrupted):
            apply(proposal, fault=self.interrupt_at("after_file", 1))
        recover()
        self.assertNotIn(b"First event", log.read_bytes())
        archive = self.root / "projects/example/log.archive.md"
        self.assertIn(b"First event", archive.read_bytes())
        self.user("rename-page", page_id=page_id, expected_hash=digest((self.root / path).read_bytes()), to="projects/renamed/renamed.md",
                  sidecars={str(p.relative_to(self.root)): digest(p.read_bytes()) for p in (log, archive)})
        self.assertTrue((self.root / "projects/renamed/log.archive.md").exists())
        self.assertFalse(log.exists())

    def test_undeclared_project_sidecar_blocks_forget(self):
        path = "projects/example/example.md"
        page_id = self.create(path=path)
        (self.root / "projects/example/notes.txt").write_text("handwritten")
        with self.assertRaises(MemoryConflict):
            self.user("forget-page", page_id=page_id, expected_hash=digest(TEXT))

    def test_export_captures_active_binary_payload_and_partial_state(self):
        from export_store import export, TABLES
        with self.assertRaises(Interrupted):
            apply(self.creation(), fault=self.interrupt_at("after_file", 0))
        destination = self.home / "export"
        export(destination)
        data = json.loads((destination / "store.json").read_text())
        self.assertTrue(set(TABLES) <= set(data))
        step = next(s for s in data["memory_steps"] if s["target_path"] == "concepts/example.md")
        self.assertEqual(base64.b64decode(step["after_bytes"]["data"]), TEXT)
        self.assertEqual((destination / "memory/concepts/example.md").read_bytes(), TEXT)

    def test_expiry_scrubs_pending_payload_and_keeps_gate(self):
        with self.assertRaises(Interrupted):
            apply(self.creation(), fault=self.interrupt_at("prepared"))
        with write_txn() as conn:
            conn.execute("UPDATE page_operations SET created_at='2000-01-01T00:00:00+00:00'")
        with self.assertRaises(MemoryBlocked):
            recover()
        self.assertTrue(all(s["after_bytes"] is None for s in self.rows("memory_steps")))
        self.assertEqual(check()["resolutions"][-1]["resolution_type"], "payload_expired")
        self.assertFalse((self.root / "concepts/example.md").exists())

    def test_reset_does_not_replay_and_rotates_store_instance(self):
        import reset
        proposal = self.creation()
        with self.assertRaises(Interrupted):
            apply(proposal, fault=self.interrupt_at("prepared"))
        core = self.home / "state.db"
        core.write_bytes(b"Hermes core store")
        lock = self.home / "workspace/.memory-operations.lock"
        inode = lock.stat().st_ino
        removed, failed, _ = reset.remove()
        self.assertFalse(failed)
        self.assertFalse(self.root.exists())
        self.assertEqual(lock.stat().st_ino, inode)
        self.assertEqual(lock.read_bytes(), b"")
        ensure_store()
        set_enabled(True)
        self.assertNotEqual(check()["store_instance_id"], self.instance)
        with self.assertRaises(MemoryConflict):
            apply(proposal)
        self.assertEqual(core.read_bytes(), b"Hermes core store")

    def test_real_process_death_after_replacement_recovers(self):
        proposal = self.creation()
        source = "import os,sys,json; sys.path.insert(0,sys.argv[1]); from memory_pages import apply; apply(json.loads(sys.argv[2]), fault=lambda p,i: os._exit(77) if (p,i)==('after_file',0) else None)"
        result = subprocess.run([sys.executable, "-c", source, str(HERE), json.dumps(proposal)], capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 77, result.stderr.decode())
        self.assertEqual(recover()["status"], "complete")
        self.assertEqual(len(self.rows("page_events")), 1)

    def test_reader_waits_for_writer_lock_without_sql_lock_inversion(self):
        marker = self.home / "reader_ready"
        script = "import sys; from pathlib import Path; sys.path.insert(0,sys.argv[1]); from memory_io import read_snapshot; Path(sys.argv[2]).write_text('ready');\nwith read_snapshot(): print('read',flush=True)"
        with memory_lock(exclusive=True):
            process = subprocess.Popen([sys.executable, "-c", script, str(HERE), str(marker)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            deadline = time.monotonic() + 5
            while not marker.exists() and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertTrue(marker.exists())
            self.assertIsNone(process.poll())
            # Reader acquired no SQLite lock while waiting for the file lock.
            with write_txn() as conn:
                conn.execute("INSERT INTO meta VALUES ('concurrency_test','ok')")
        stdout, stderr = process.communicate(timeout=10)
        self.assertEqual(process.returncode, 0, stderr.decode())
        self.assertEqual(stdout.strip(), b"read")

    def test_death_between_no_clobber_link_and_temporary_unlink_recovers(self):
        proposal = self.creation()
        source = """import os,sys,json
sys.path.insert(0,sys.argv[1])
from memory_pages import apply
import memory_io
original = memory_io.os.link
def crash(*args, **kwargs):
    original(*args, **kwargs)
    os._exit(78)
memory_io.os.link = crash
apply(json.loads(sys.argv[2]))
"""
        result = subprocess.run([sys.executable, "-c", source, str(HERE), json.dumps(proposal)], capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 78, result.stderr.decode())
        self.assertEqual(recover()["status"], "complete")
        self.assertEqual((self.root / "concepts/example.md").stat().st_nlink, 1)
        self.assertFalse(list(self.root.rglob(".memory-*")))

    def test_completion_callback_cannot_commit_independently(self):
        journal.register_completion("test.commit.v1", required_tables=[], validate=lambda *a: None,
                                    apply=lambda conn, *a: conn.commit())
        with self.assertRaises(sqlite3.DatabaseError):
            apply(self.creation(), completion=[{"handler": "test.commit.v1"}])
        self.assertEqual(self.rows("page_events"), [])
        self.assertEqual(self.rows("managed_fields"), [])
        self.assertNotEqual(check()["status"], "clean")

    def test_completion_validator_is_read_only(self):
        def validate(conn, *args):
            conn.execute("UPDATE memory_control SET enabled=0")
        journal.register_completion("test.validate.v1", required_tables=[], validate=validate, apply=lambda *a: None)
        with self.assertRaises(sqlite3.DatabaseError):
            apply(self.creation(), completion=[{"handler": "test.validate.v1"}])
        self.assertTrue(check()["enabled"])
        self.assertEqual(self.rows("page_operations"), [])

    def test_new_capture_during_publication_is_seen_by_completion_and_reader(self):
        with write_txn() as conn:
            conn.execute("CREATE TABLE test_capture(revision INTEGER)")
            conn.execute("INSERT INTO test_capture VALUES (1)")
            conn.execute("CREATE TABLE test_projection(basis INTEGER,obsolete INTEGER)")
        def complete(conn, effect, operation):
            current = conn.execute("SELECT revision FROM test_capture").fetchone()[0]
            conn.execute("INSERT INTO test_projection VALUES (?,?)", (effect["basis"], int(current != effect["basis"])))
        def guard(conn):
            if conn.execute("SELECT 1 FROM test_projection WHERE obsolete=1").fetchone():
                raise MemoryBlocked("projection requires current feedback")
        journal.register_completion("test.project.v1", required_tables=["test_capture", "test_projection"],
                                    validate=lambda *a: None, apply=complete, read_guard=guard)
        def capture(point, ordinal):
            if point == "prepared":
                # This path is deliberately SQLite-only while publication
                # holds the memory lock. It represents a future capture API.
                with write_txn() as conn:
                    conn.execute("UPDATE test_capture SET revision=2")
        apply(self.creation(), completion=[{"handler": "test.project.v1", "basis": 1}], fault=capture)
        self.assertEqual(self.rows("test_projection"), [{"basis": 1, "obsolete": 1}])
        with self.assertRaises(MemoryBlocked):
            snapshot(["concepts/example.md"])

    def test_compensating_replacement_preserves_reviewed_live_content(self):
        with self.assertRaises(Interrupted):
            apply(self.creation(), fault=self.interrupt_at("after_file", 0))
        path = self.root / "concepts/example.md"
        path.write_bytes(b"User chose to keep this text.\n")
        with self.assertRaises(MemoryBlocked):
            recover()
        operation_id = check()["operation_id"]
        actual = {s["target_path"]: ((self.root / s["target_path"]).read_bytes() if (self.root / s["target_path"]).exists() else None)
                  for s in self.rows("memory_steps") if s["target_path"]}
        with self.assertRaises(MemoryConflict):
            self.user("resolve-memory-conflict", operation_id=operation_id, choice="cancel", observed={p: digest(b) for p, b in actual.items()})
        result = self.user("resolve-memory-conflict", operation_id=operation_id, choice="replace",
                           observed={p: digest(b) for p, b in actual.items()},
                           replacement={p: b.decode() if b is not None else None for p, b in actual.items()})
        self.assertEqual(result["status"], "complete")
        self.assertEqual(path.read_bytes(), b"User chose to keep this text.\n")
        self.assertEqual(self.rows("managed_fields"), [])
        self.assertEqual(self.rows("page_operations")[0]["status"], "superseded")
        self.assertEqual(self.rows("page_operations")[1]["supersedes_id"], operation_id)
        page_id = self.create(path="concepts/reviewed.md")
        proposal = self.proposal("update", changes=[{"page_id": page_id, "expected_hash": digest(TEXT),
                  "fields": {"section:Definition": "## Definition\nProposed text.\n"}}])
        with self.assertRaises(Interrupted):
            apply(proposal, fault=self.interrupt_at("after_file", 0))
        reviewed = self.root / "concepts/reviewed.md"
        reviewed.write_bytes(TEXT.replace(b"useful", b"user-chosen"))
        with self.assertRaises(MemoryBlocked):
            recover()
        from memory_operations import inspect_operation
        inspection = inspect_operation()
        self.assertFalse(inspection["current_memory"])
        self.user("resolve-memory-conflict", operation_id=inspection["operation_id"], choice="replace",
                  observed=inspection["observed"], replacement=inspection["files"])
        self.assertIn(b"user-chosen", reviewed.read_bytes())
        # The reviewed replacement establishes a CAS baseline; it does not
        # leave the same unexplained-divergence failure on every later pass.
        self.update(page_id, path="concepts/reviewed.md")

    def test_two_competing_writers_serialize_without_losing_index_entries(self):
        source = "import sys,json;sys.path.insert(0,sys.argv[1]);from memory_pages import apply;print(apply(json.loads(sys.argv[2])))"
        proposals = [self.creation(path=f"concepts/concurrent_{i}.md") for i in range(2)]
        processes = [subprocess.Popen([sys.executable, "-c", source, str(HERE), json.dumps(p)], stdout=subprocess.PIPE, stderr=subprocess.PIPE) for p in proposals]
        for process in processes:
            stdout, stderr = process.communicate(timeout=20)
            self.assertEqual(process.returncode, 0, stderr.decode())
        index = (self.root / "index.md").read_text()
        for i in range(2):
            self.assertIn(f"concepts/concurrent_{i}.md", index)
        self.assertEqual(len(self.rows("page_events")), 2)

    def test_legacy_adapter_cannot_rewrite_managed_project_sidecars(self):
        self.create(path="projects/example/example.md", sidecars={"log.md": {"expected_hash": None, "entries": {"one": "First."}}})
        path = self.root / "projects/example/log.md"
        with self.assertRaises(MemoryConflict):
            apply(self.proposal("legacy_write", skill="memory-repair", changes=[{"path": "projects/example/log.md", "expected_hash": digest(path.read_bytes()), "text": "Rewritten."}]))

    def test_registered_repair_works_while_generation_is_disabled(self):
        page_id = self.create()
        set_enabled(False)
        result = apply(self.proposal("update", skill="memory-repair", changes=[{"page_id": page_id,
                       "expected_hash": digest(TEXT), "fields": {"section:Definition": "## Definition\nRepaired.\n"}}]))
        self.assertEqual(result["status"], "complete")

    def test_evidence_receipts_validate_references_without_copying_source_text(self):
        with write_txn() as conn:
            conn.execute("INSERT INTO items(source_id,source,scope,event_at,body,state) VALUES ('message','email','inbox','2026-01-01','private source text','pending')")
        proposal = self.creation()
        proposal["evidence_refs"] = ["item:message"]
        apply(proposal)
        self.assertEqual({r["last_evidence_digest"] for r in self.rows("managed_fields")}, {journal.json_digest(["item:message"])})
        self.assertNotIn("private source text", json.dumps(self.rows("page_operations")))
        invalid = self.creation(path="concepts/other.md")
        invalid["evidence_refs"] = ["item:missing"]
        with self.assertRaises(MemoryConflict):
            apply(invalid)


if __name__ == "__main__":
    unittest.main(verbosity=2)
