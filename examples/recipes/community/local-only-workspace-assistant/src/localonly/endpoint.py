# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Reject an inference base URL that does not point at this machine.

The OpenShell gateway, not the sandbox, sends prompts to the inference
endpoint. The sandbox egress policy does not apply to the gateway, so setup
calls this check before it registers the endpoint. The check is syntactic. It
does not resolve names and it does not prove where a name resolves.
"""

from __future__ import annotations

import ipaddress
from typing import Iterable
from urllib.parse import urlsplit

# Names that refer to the local machine from the host, from a Docker
# container, or from an OpenShell sandbox.
LOCAL_HOSTNAMES = frozenset({"localhost", "host.docker.internal", "host.openshell.internal"})


class EndpointRejected(ValueError):
    """The URL is not an accepted local inference endpoint."""


def _normalize(host: str) -> str:
    return host.strip().lower().rstrip(".")


def check_local_endpoint(url: str, extra_hosts: Iterable[str] = ()) -> str:
    """Return the normalized host of a local endpoint URL.

    `extra_hosts` lists additional exact hosts that the operator accepts, such
    as the address of a Docker bridge on this machine. Raise `EndpointRejected`
    for every other URL.
    """
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https"):
        raise EndpointRejected("scheme must be http or https")
    if parts.username is not None or parts.password is not None:
        raise EndpointRejected("URL must not contain user information")
    try:
        raw_host = parts.hostname
        parts.port  # Reading the port validates it.
    except ValueError as exc:
        raise EndpointRejected("URL has an invalid host or port") from exc
    if not raw_host:
        raise EndpointRejected("URL has no host")

    host = _normalize(raw_host)
    accepted = {_normalize(item) for item in extra_hosts if item.strip()}

    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None

    if address is None:
        if host in LOCAL_HOSTNAMES or host in accepted:
            return host
        raise EndpointRejected("host is not a local name: " + host)

    mapped = getattr(address, "ipv4_mapped", None)
    if mapped is not None:
        address = mapped
    if address.is_unspecified:
        raise EndpointRejected("host must not be the unspecified address")
    if address.is_loopback or str(address) in accepted or host in accepted:
        return str(address)
    raise EndpointRejected("address is not loopback: " + str(address))


def check_publish_host(host: str) -> str:
    """Return a publish address that does not expose a port on every interface."""
    normalized = _normalize(host)
    try:
        address = ipaddress.ip_address(normalized)
    except ValueError as exc:
        raise EndpointRejected("publish host must be an IP address") from exc
    if address.is_unspecified:
        raise EndpointRejected("publish host must not be the unspecified address")
    return str(address)
