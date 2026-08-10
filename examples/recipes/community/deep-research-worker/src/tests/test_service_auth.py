# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

import os
import tempfile
import unittest

_TEST_STATE = tempfile.TemporaryDirectory(prefix="deep-research-auth-")
os.environ["DEEPAGENTS_STATE_DIR"] = _TEST_STATE.name
os.environ["DEEPAGENTS_SERVICE_SECRET"] = "test-worker-secret"

from fastapi.testclient import TestClient

import service


class ServiceAuthenticationTests(unittest.TestCase):
    def setUp(self) -> None:
        service.config["service_secret"] = "test-worker-secret"
        self.client = TestClient(service.app)

    def test_health_is_public(self) -> None:
        self.assertEqual(self.client.get("/healthz").status_code, 200)

    def test_task_endpoint_rejects_missing_credentials(self) -> None:
        response = self.client.post("/v1/tasks", json={"prompt": "research this"})
        self.assertEqual(response.status_code, 401)

    def test_task_endpoint_rejects_invalid_credentials(self) -> None:
        response = self.client.get(
            "/v1/tasks",
            headers={"Authorization": "Bearer wrong-secret"},
        )
        self.assertEqual(response.status_code, 403)

    def test_task_endpoint_fails_closed_when_secret_is_not_configured(self) -> None:
        service.config["service_secret"] = ""
        response = self.client.get("/v1/tasks")
        self.assertEqual(response.status_code, 503)

    def test_task_endpoint_accepts_valid_credentials(self) -> None:
        response = self.client.get(
            "/v1/tasks",
            headers={"Authorization": "Bearer test-worker-secret"},
        )
        self.assertEqual(response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
