# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Exercise the generated HTTP probes without contacting a server."""

import contextlib
import errno
import io
import os
import shlex
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from localonly.backends import ExecResult
from localonly.cases import CASES
from localonly.runner import FAIL, INCONCLUSIVE, PASS, judge

BY_ID = {case.case_id: case for case in CASES}
CURL_CASES = ("S06", "S06b", "S09", "S09c")


def python_result(case_id, *, response=None, error=None):
    output = io.StringIO()
    environment = {"OPENAI_BASE_URL": "http://localhost:11434/v1", "INFERENCE_MODEL": "test"}
    with patch.dict(os.environ, environment), contextlib.redirect_stdout(output):
        with patch("urllib.request.urlopen", return_value=response, side_effect=error) as request:
            try:
                exec(shlex.split(BY_ID[case_id].script)[2], {})
                status = 0
            except SystemExit as stopped:
                status = stopped.code
            except URLError as failure:
                print(failure)
                status = 1
            request.assert_called_once()
    return ExecResult(status, output.getvalue())


class NetworkProbeTests(unittest.TestCase):
    def test_python_origin_error_body_is_not_connection_denial(self):
        for code in (403, 500):
            for body in (b"Permission denied", b'{"error":"policy_denied"}'):
                with self.subTest(code=code, body=body):
                    error = HTTPError("http://example.com", code, "Forbidden", {}, io.BytesIO(body))
                    result = python_result("S06c", error=error)
                    self.assertEqual(judge(BY_ID["S06c"], result).verdict, INCONCLUSIVE)

    def test_python_eacces_is_a_connection_denial(self):
        error = URLError(PermissionError(errno.EACCES, "Permission denied"))
        result = python_result("S06c", error=error)
        self.assertEqual(result.exit_code, 13)
        self.assertEqual(judge(BY_ID["S06c"], result).verdict, PASS)

    def test_python_other_connection_errors_are_inconclusive(self):
        for reason in (ConnectionRefusedError(errno.ECONNREFUSED, "Connection refused"),
                       TimeoutError("timed out"), "Permission denied"):
            with self.subTest(reason=reason):
                result = python_result("S06c", error=URLError(reason))
                self.assertEqual(judge(BY_ID["S06c"], result).verdict, INCONCLUSIVE)

    def test_python_success_is_not_denial_even_with_matching_body(self):
        result = python_result("S06c", response=io.BytesIO(b"Permission denied policy_denied"))
        self.assertEqual(judge(BY_ID["S06c"], result).verdict, FAIL)

    def test_curl_origin_error_body_is_not_connection_denial(self):
        for case_id in CURL_CASES:
            for body in ("Permission denied", '{"error":"policy_denied"}'):
                with self.subTest(case=case_id, body=body):
                    result = ExecResult(22, "< HTTP/1.1 403 Forbidden\n" + body)
                    self.assertEqual(judge(BY_ID[case_id], result).verdict, INCONCLUSIVE)

    def test_curl_requires_connection_failure_and_permission_denial(self):
        for case_id in CURL_CASES:
            for result, verdict in (
                (ExecResult(7, "Immediate connect fail: Permission denied"), PASS),
                (ExecResult(7, "Connection refused"), INCONCLUSIVE),
                (ExecResult(28, "timed out"), INCONCLUSIVE),
                (ExecResult(0, "Permission denied"), FAIL),
            ):
                with self.subTest(case=case_id, result=result):
                    self.assertEqual(judge(BY_ID[case_id], result).verdict, verdict)

    def test_local_provider_policy_denial_still_passes(self):
        body = b'{"error":"policy_denied","rule":"POST /api/pull"}'
        error = HTTPError("http://localhost:11434/api/pull", 403, "Forbidden", {}, io.BytesIO(body))
        result = python_result("S09b", error=error)
        self.assertEqual(judge(BY_ID["S09b"], result).verdict, PASS)

    def test_stopped_server_and_allowed_chat_keep_their_verdicts(self):
        for case_id, verdict in (("S00", FAIL), ("S08", PASS)):
            result = python_result(case_id, error=URLError(TimeoutError("timed out")))
            self.assertEqual(judge(BY_ID[case_id], result).verdict, verdict)
        response = io.BytesIO(b'{"choices":[{"message":{"content":"pong"}}]}')
        self.assertEqual(judge(BY_ID["S00"], python_result("S00", response=response)).verdict, PASS)


if __name__ == "__main__":
    unittest.main()
