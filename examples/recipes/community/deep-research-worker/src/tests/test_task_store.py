# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta

from task_store import TaskStore


class TaskStoreRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = TaskStore(self.temp_dir.name, ttl_hours=1)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_restart_recovers_running_and_cancelling_tasks(self) -> None:
        running = self.store.enqueue("running")
        self.assertEqual(self.store.claim_next()["task_id"], running["task_id"])

        cancelling = self.store.enqueue("cancelling")
        claimed = self.store.claim_next()
        self.assertEqual(claimed["task_id"], cancelling["task_id"])
        self.store.mark_cancelling(cancelling["task_id"])

        recovered = self.store.recover_inflight()

        self.assertEqual(recovered, {"failed": 1, "cancelled": 1})
        self.assertEqual(self.store.get_task(running["task_id"])["status"], "failed")
        self.assertEqual(self.store.get_task(cancelling["task_id"])["status"], "cancelled")
        self.assertIsNone(self.store.claim_next())

    def test_cleanup_removes_only_expired_terminal_tasks(self) -> None:
        terminal = self.store.enqueue("terminal")
        self.store.claim_next()
        self.store.update_result(terminal["task_id"], "completed", result="done")
        running = self.store.enqueue("still running")
        self.store.claim_next()
        old = (datetime.utcnow() - timedelta(hours=2)).isoformat()
        with closing(self.store._get_connection()) as conn:
            conn.execute(
                "UPDATE tasks SET completed_at = ? WHERE task_id = ?",
                (old, terminal["task_id"]),
            )
            conn.execute(
                "UPDATE tasks SET created_at = ? WHERE task_id = ?",
                (old, running["task_id"]),
            )
            conn.commit()

        self.assertEqual(self.store.cleanup_expired(), 1)
        self.assertIsNone(self.store.get_task(terminal["task_id"]))
        self.assertEqual(self.store.get_task(running["task_id"])["status"], "running")

    def test_cancelling_state_cannot_be_overwritten_by_child_completion(self) -> None:
        task = self.store.enqueue("cancel race")
        self.store.claim_next()
        self.store.mark_cancelling(task["task_id"])

        self.assertFalse(
            self.store.update_result(task["task_id"], "completed", result="late result")
        )
        self.assertEqual(self.store.get_task(task["task_id"])["status"], "cancelling")


if __name__ == "__main__":
    unittest.main()
