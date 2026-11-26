# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""A remote inference endpoint is rejected before setup registers it."""

import unittest

from localonly.endpoint import EndpointRejected, check_local_endpoint, check_publish_host


class LocalEndpointTests(unittest.TestCase):
    def test_accepts_local_endpoints(self):
        for url in (
            "http://127.0.0.1:11434/v1",
            "http://localhost:11434/v1",
            "http://LOCALHOST.:11434/v1",
            "http://[::1]:11434/v1",
            "http://host.docker.internal:11434/v1",
            "http://host.openshell.internal:11434/v1",
        ):
            with self.subTest(url=url):
                check_local_endpoint(url)

    def test_rejects_remote_endpoints(self):
        for url in (
            "https://api.openai.com/v1",
            "https://integrate.api.nvidia.com/v1",
            "http://192.168.1.20:11434/v1",
            "http://10.0.0.5:11434/v1",
            "http://0.0.0.0:11434/v1",
            "http://[::]:11434/v1",
        ):
            with self.subTest(url=url):
                with self.assertRaises(EndpointRejected):
                    check_local_endpoint(url)

    def test_rejects_urls_that_look_local(self):
        for url in (
            "http://127.0.0.1.example.com:11434/v1",
            "http://localhost.example.com/v1",
            "http://localhost@example.com/v1",
            "http://127.0.0.1:11434@example.com/v1",
            "http://2130706433/v1",
            "http://0x7f000001/v1",
            "ftp://127.0.0.1/v1",
            "127.0.0.1:11434/v1",
            "http:///v1",
            "",
        ):
            with self.subTest(url=url):
                with self.assertRaises(EndpointRejected):
                    check_local_endpoint(url)

    def test_ipv4_mapped_loopback_follows_the_ipv4_rule(self):
        check_local_endpoint("http://[::ffff:127.0.0.1]:11434/v1")
        with self.assertRaises(EndpointRejected):
            check_local_endpoint("http://[::ffff:192.168.1.20]:11434/v1")

    def test_operator_can_accept_an_exact_extra_host(self):
        with self.assertRaises(EndpointRejected):
            check_local_endpoint("http://172.18.0.1:11434/v1")
        self.assertEqual(
            check_local_endpoint("http://172.18.0.1:11434/v1", ["172.18.0.1"]), "172.18.0.1",
        )
        with self.assertRaises(EndpointRejected):
            check_local_endpoint("http://172.18.0.2:11434/v1", ["172.18.0.1"])


class PublishHostTests(unittest.TestCase):
    def test_accepts_one_interface(self):
        self.assertEqual(check_publish_host("127.0.0.1"), "127.0.0.1")
        self.assertEqual(check_publish_host("172.18.0.1"), "172.18.0.1")

    def test_rejects_every_interface(self):
        for host in ("0.0.0.0", "::", "", "localhost"):
            with self.subTest(host=host):
                with self.assertRaises(EndpointRejected):
                    check_publish_host(host)


if __name__ == "__main__":
    unittest.main()
