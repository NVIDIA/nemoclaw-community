# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Minimal Kubernetes API client with two interchangeable transports.

* ``HttpTransport`` talks to the API server directly with the standard library
  (in-cluster ServiceAccount token, or ``SRE_AUTOHEAL_KUBE_API`` /
  ``SRE_AUTOHEAL_KUBE_TOKEN``/``_TOKEN_FILE`` / ``SRE_AUTOHEAL_KUBE_CA``).
  No third-party dependency, so the agent runs unmodified on a plain
  ``python:3.12`` image.
* ``KubectlTransport`` shells out to ``kubectl``/``oc`` and inherits the
  caller's kubeconfig/context. Used for local runs and inside a Hermes
  sandbox whose only credential is a wrapper binary.

Every write goes through this module so RBAC and audit stay in one place.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import ssl
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

SA_TOKEN = "/var/run/secrets/kubernetes.io/serviceaccount/token"
SA_CA = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
SA_NS = "/var/run/secrets/kubernetes.io/serviceaccount/namespace"

MERGE_PATCH = "application/merge-patch+json"
STRATEGIC_PATCH = "application/strategic-merge-patch+json"
JSON_PATCH = "application/json-patch+json"


class KubeError(RuntimeError):
    def __init__(self, message: str, status: int = 0, body: str = ""):
        super().__init__(message)
        self.status = status
        self.body = body


class KubeForbidden(KubeError):
    pass


class KubeNotFound(KubeError):
    pass


@dataclass(frozen=True)
class ResourceRef:
    """Addresses one API resource. ``group`` is '' for the core group."""

    group: str
    version: str
    resource: str
    namespace: Optional[str] = None
    name: Optional[str] = None
    subresource: Optional[str] = None

    @property
    def api_version(self) -> str:
        return f"{self.group}/{self.version}" if self.group else self.version

    def path(self, query: Optional[Dict[str, str]] = None) -> str:
        base = f"/api/{self.version}" if not self.group else f"/apis/{self.group}/{self.version}"
        parts = [base]
        if self.namespace:
            parts.append(f"namespaces/{urllib.parse.quote(self.namespace)}")
        parts.append(self.resource)
        if self.name:
            parts.append(urllib.parse.quote(self.name))
        if self.subresource:
            parts.append(self.subresource)
        url = "/".join(parts)
        if query:
            url += "?" + urllib.parse.urlencode(query)
        return url


# Common resource shorthands -------------------------------------------------
PODS = ResourceRef("", "v1", "pods")
NODES = ResourceRef("", "v1", "nodes")
EVENTS = ResourceRef("", "v1", "events")
NAMESPACES = ResourceRef("", "v1", "namespaces")
PVCS = ResourceRef("", "v1", "persistentvolumeclaims")
SERVICES = ResourceRef("", "v1", "services")
ENDPOINTS = ResourceRef("", "v1", "endpoints")
CONFIGMAPS = ResourceRef("", "v1", "configmaps")
RESOURCEQUOTAS = ResourceRef("", "v1", "resourcequotas")
DEPLOYMENTS = ResourceRef("apps", "v1", "deployments")
REPLICASETS = ResourceRef("apps", "v1", "replicasets")
STATEFULSETS = ResourceRef("apps", "v1", "statefulsets")
DAEMONSETS = ResourceRef("apps", "v1", "daemonsets")
JOBS = ResourceRef("batch", "v1", "jobs")
HPAS = ResourceRef("autoscaling", "v2", "horizontalpodautoscalers")
PDBS = ResourceRef("policy", "v1", "poddisruptionbudgets")
CLUSTEROPERATORS = ResourceRef("config.openshift.io", "v1", "clusteroperators")
MACHINECONFIGPOOLS = ResourceRef("machineconfiguration.openshift.io", "v1", "machineconfigpools")
CSRS = ResourceRef("certificates.k8s.io", "v1", "certificatesigningrequests")

KIND_TO_REF = {
    "Pod": PODS,
    "Node": NODES,
    "Deployment": DEPLOYMENTS,
    "ReplicaSet": REPLICASETS,
    "StatefulSet": STATEFULSETS,
    "DaemonSet": DAEMONSETS,
    "Job": JOBS,
    "PersistentVolumeClaim": PVCS,
    "Service": SERVICES,
    "HorizontalPodAutoscaler": HPAS,
    "ConfigMap": CONFIGMAPS,
}


def ref_for_kind(kind: str, namespace: Optional[str] = None, name: Optional[str] = None,
                 subresource: Optional[str] = None) -> ResourceRef:
    base = KIND_TO_REF.get(kind)
    if base is None:
        raise KubeError(f"unsupported kind for remediation: {kind}")
    return ResourceRef(base.group, base.version, base.resource, namespace, name, subresource)


# Transports -----------------------------------------------------------------
class Transport:
    name = "abstract"

    def request(self, method: str, path: str, body: Any = None,
                content_type: str = "application/json", ref: Optional["ResourceRef"] = None,
                dry_run: bool = False) -> Any:
        """Perform one API call. ``ref`` is the structured form of ``path`` when known.

        ``dry_run`` requests server-side validation only (``?dryRun=All``)."""
        raise NotImplementedError

    def whoami(self) -> str:
        return "unknown"


class HttpTransport(Transport):
    name = "http"

    def __init__(self, api_server: str, token: str, ca_file: Optional[str], timeout: int = 30,
                 insecure: bool = False, token_file: Optional[str] = None):
        self.api_server = api_server.rstrip("/")
        self._token = token
        self._token_file = token_file
        self.timeout = timeout
        if insecure:
            self.ctx = ssl._create_unverified_context()  # noqa: S323 - explicit operator opt-in
        else:
            self.ctx = ssl.create_default_context(cafile=ca_file) if ca_file else ssl.create_default_context()

    @classmethod
    def from_environment(cls, timeout: int = 30) -> Optional["HttpTransport"]:
        env = os.environ
        api = env.get("SRE_AUTOHEAL_KUBE_API")
        token = env.get("SRE_AUTOHEAL_KUBE_TOKEN")
        token_file = env.get("SRE_AUTOHEAL_KUBE_TOKEN_FILE")
        ca = env.get("SRE_AUTOHEAL_KUBE_CA")
        insecure = env.get("SRE_AUTOHEAL_KUBE_INSECURE", "").lower() in {"1", "true"}
        if not api and env.get("KUBERNETES_SERVICE_HOST"):
            host = env["KUBERNETES_SERVICE_HOST"]
            port = env.get("KUBERNETES_SERVICE_PORT", "443")
            api = f"https://{host}:{port}"
            token_file = token_file or SA_TOKEN
            ca = ca or SA_CA
        if not api:
            return None
        # An explicit token takes precedence over a file. Otherwise retain the
        # path, not just its initial contents: kubelet rotates projected tokens.
        reload_file = token_file if not token else None
        if reload_file:
            token = cls._read_token(reload_file)
        if not token:
            return None
        ca_file = ca if ca and os.path.isfile(ca) else None
        return cls(api, token, ca_file, timeout=timeout, insecure=insecure, token_file=reload_file)

    @staticmethod
    def _read_token(path: str) -> str:
        try:
            with open(path, encoding="utf-8") as fh:
                token = fh.read().strip()
        except (OSError, UnicodeError):
            raise KubeError("cannot read Kubernetes API token file") from None
        if not token:
            raise KubeError("Kubernetes API token file is empty")
        return token

    def request(self, method: str, path: str, body: Any = None,
                content_type: str = "application/json", ref: Optional["ResourceRef"] = None,
                dry_run: bool = False) -> Any:
        data = None
        # Reopen the projected path on each request, including after an atomic
        # symlink replacement. A failed read must not reuse a stale credential.
        token = self._read_token(self._token_file) if self._token_file else self._token
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = content_type
        req = urllib.request.Request(self.api_server + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout, context=self.ctx) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            raw_body = exc.read().decode("utf-8", "replace")
            message = f"{method} {path} -> HTTP {exc.code}"
            if exc.code == 403:
                raise KubeForbidden(message, exc.code, raw_body) from None
            if exc.code == 404:
                raise KubeNotFound(message, exc.code, raw_body) from None
            raise KubeError(message + f": {raw_body[:300]}", exc.code, raw_body) from None
        except urllib.error.URLError as exc:
            raise KubeError(f"{method} {path} failed: {exc.reason}") from None
        if not raw:
            return None
        text = raw.decode("utf-8", "replace")
        if text.startswith("{") or text.startswith("["):
            return json.loads(text)
        return text

    def whoami(self) -> str:
        try:
            review = self.request("POST", "/apis/authentication.k8s.io/v1/selfsubjectreviews",
                                  {"apiVersion": "authentication.k8s.io/v1", "kind": "SelfSubjectReview"})
            return review.get("status", {}).get("userInfo", {}).get("username", "unknown")
        except KubeError:
            return "unknown"


class KubectlTransport(Transport):
    name = "kubectl"

    def __init__(self, binary: Optional[str] = None, timeout: int = 60):
        self.binary = binary or shutil.which("kubectl") or shutil.which("oc")
        if not self.binary:
            raise KubeError("neither kubectl nor oc found on PATH")
        self.timeout = timeout

    def _run(self, args: List[str], stdin: Optional[str] = None) -> str:
        cmd = [self.binary] + args
        log.debug("exec: %s", " ".join(cmd))
        proc = subprocess.run(cmd, input=stdin, capture_output=True, text=True, timeout=self.timeout)
        if proc.returncode != 0:
            err = proc.stderr.strip()
            lowered = err.lower()
            if "forbidden" in lowered:
                raise KubeForbidden(err, 403, err)
            if "notfound" in lowered or "not found" in lowered:
                raise KubeNotFound(err, 404, err)
            raise KubeError(err or f"{self.binary} exited {proc.returncode}", proc.returncode, err)
        return proc.stdout

    def request(self, method: str, path: str, body: Any = None,
                content_type: str = "application/json", ref: Optional["ResourceRef"] = None,
                dry_run: bool = False) -> Any:
        # kubectl exposes the raw REST surface for get/delete/create/replace via
        # --raw. `kubectl patch` has no --raw, so PATCH needs the structured ref.
        if method == "GET":
            args = ["get", "--raw", path]
        elif method == "PATCH":
            if ref is None or not ref.name:
                raise KubeError("kubectl transport needs a named ResourceRef for PATCH")
            target = ref.resource if not ref.group else f"{ref.resource}.{ref.version}.{ref.group}"
            args = ["patch", target, ref.name, "--type", _patch_type_flag(content_type), "-p", json.dumps(body)]
            if ref.namespace:
                args += ["-n", ref.namespace]
            if ref.subresource:
                args += [f"--subresource={ref.subresource}"]
            if dry_run:
                args += ["--dry-run=server"]
            args += ["-o", "json"]
        elif method == "DELETE":
            args = ["delete", "--raw", path]
        elif method == "POST":
            args = ["create", "--raw", path, "-f", "-"]
        elif method == "PUT":
            args = ["replace", "--raw", path, "-f", "-"]
        else:  # pragma: no cover
            raise KubeError(f"unsupported method {method}")
        stdin = json.dumps(body) if method in {"POST", "PUT"} and body is not None else None
        out = self._run(args, stdin=stdin)
        out = out.strip()
        if not out:
            return None
        if out.startswith("{") or out.startswith("["):
            return json.loads(out)
        return out

    def whoami(self) -> str:
        try:
            return self._run(["auth", "whoami", "-o", "jsonpath={.status.userInfo.username}"]).strip() or "unknown"
        except KubeError:
            try:
                return self._run(["whoami"]).strip()
            except KubeError:
                return "unknown"


def _patch_type_flag(content_type: str) -> str:
    return {MERGE_PATCH: "merge", STRATEGIC_PATCH: "strategic", JSON_PATCH: "json"}.get(content_type, "merge")


# Client ---------------------------------------------------------------------
class KubeClient:
    def __init__(self, transport: Transport):
        self.transport = transport
        self._platform: Optional[str] = None
        self._api_cache: Dict[str, bool] = {}

    @classmethod
    def build(cls, transport: str = "auto", kubectl_binary: str = "", timeout: int = 30) -> "KubeClient":
        if transport in {"auto", "http"}:
            http = HttpTransport.from_environment(timeout=timeout)
            if http:
                return cls(http)
            if transport == "http":
                raise KubeError("http transport requested but no in-cluster token or SRE_AUTOHEAL_KUBE_* env found")
        return cls(KubectlTransport(kubectl_binary or None, timeout=max(timeout, 60)))

    # -- generic -------------------------------------------------------------
    def get(self, ref: ResourceRef, query: Optional[Dict[str, str]] = None) -> Any:
        return self.transport.request("GET", ref.path(query))

    def list(self, ref: ResourceRef, label_selector: str = "", field_selector: str = "",
             limit: int = 0) -> List[Dict[str, Any]]:
        query: Dict[str, str] = {}
        if label_selector:
            query["labelSelector"] = label_selector
        if field_selector:
            query["fieldSelector"] = field_selector
        if limit:
            query["limit"] = str(limit)
        items: List[Dict[str, Any]] = []
        while True:
            page = self.transport.request("GET", ref.path(query or None)) or {}
            items.extend(page.get("items", []) or [])
            cont = (page.get("metadata") or {}).get("continue")
            if not cont:
                break
            query["continue"] = cont
        return items

    def patch(self, ref: ResourceRef, body: Any, content_type: str = MERGE_PATCH, dry_run: bool = False) -> Any:
        query = {"dryRun": "All"} if dry_run else None
        return self.transport.request("PATCH", ref.path(query), body, content_type, ref=ref, dry_run=dry_run)

    def delete(self, ref: ResourceRef, grace_period: Optional[int] = None) -> Any:
        query = {"gracePeriodSeconds": str(grace_period)} if grace_period is not None else None
        return self.transport.request("DELETE", ref.path(query))

    def create(self, ref: ResourceRef, body: Any) -> Any:
        return self.transport.request("POST", ref.path(), body)

    def replace(self, ref: ResourceRef, body: Any) -> Any:
        return self.transport.request("PUT", ref.path(), body)

    def pod_logs(self, namespace: str, name: str, container: str, tail: int = 40, previous: bool = False) -> str:
        query = {"container": container, "tailLines": str(tail)}
        if previous:
            query["previous"] = "true"
        try:
            out = self.transport.request("GET", ResourceRef("", "v1", "pods", namespace, name, "log").path(query))
        except KubeError as exc:
            return f"<logs unavailable: {str(exc)[:120]}>"
        if out is None:
            return ""
        return out if isinstance(out, str) else json.dumps(out)

    # -- discovery -----------------------------------------------------------
    def has_api(self, group: str, version: str) -> bool:
        key = f"{group}/{version}"
        if key not in self._api_cache:
            try:
                self.transport.request("GET", f"/apis/{group}/{version}")
                self._api_cache[key] = True
            except KubeError:
                self._api_cache[key] = False
        return self._api_cache[key]

    def platform(self) -> str:
        if self._platform is None:
            self._platform = "openshift" if self.has_api("config.openshift.io", "v1") else "kubernetes"
        return self._platform

    def server_version(self) -> str:
        try:
            info = self.transport.request("GET", "/version") or {}
            return info.get("gitVersion", "unknown")
        except KubeError:
            return "unknown"

    def whoami(self) -> str:
        return self.transport.whoami()

    def can_i(self, verb: str, resource: str, group: str = "", namespace: str = "",
              subresource: str = "", name: str = "") -> bool:
        attributes = {"verb": verb, "resource": resource, "group": group,
                      "namespace": namespace, "subresource": subresource}
        if name:
            # Roles scoped with resourceNames only answer "yes" for the named object.
            attributes["name"] = name
        body = {
            "apiVersion": "authorization.k8s.io/v1",
            "kind": "SelfSubjectAccessReview",
            "spec": {"resourceAttributes": attributes},
        }
        try:
            result = self.transport.request("POST", "/apis/authorization.k8s.io/v1/selfsubjectaccessreviews", body)
            return bool((result or {}).get("status", {}).get("allowed"))
        except KubeError:
            return False

    def current_namespace(self) -> str:
        if os.path.isfile(SA_NS):
            with open(SA_NS, encoding="utf-8") as fh:
                return fh.read().strip()
        return os.environ.get("SRE_AUTOHEAL_NAMESPACE", "default")
