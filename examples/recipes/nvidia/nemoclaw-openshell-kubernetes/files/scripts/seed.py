# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Safely seed chart-owned Hermes state on the retained PVC."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import ssl
import tarfile
import tempfile
from urllib.parse import urlsplit


STATE = Path("/state")
MARKER = STATE / ".nemoclaw-helm-owner.json"
RELEASE = os.environ["RELEASE_ID"]
RELEASE_REVISION = int(os.environ["RELEASE_REVISION"])
PROXY_TOKEN_SOURCE = Path("/proxy-auth/token")
PROXY_TOKEN_DESTINATION = STATE / "hermes" / ".sre-proxy-token"
PROXY_CA_SOURCE = Path("/proxy-tls-ca/ca.crt")
BUNDLE_SOURCE = Path("/skills-bundle")
CLI_SOURCE = Path("/cli-staging")
SRE_KUBECONFIG_DESTINATION = STATE / "hermes" / "sre-kubeconfig"
MODEL_DELETE_KUBECONFIG_DESTINATION = STATE / "hermes" / "model-delete-kubeconfig"
METRICS_KUBECONFIG_DESTINATION = STATE / "hermes" / "metrics-kubeconfig"
DIRECTORY_MODE = 0o700
PROXY_TOKEN_MODE = 0o600
MAX_ARCHIVE_BYTES = 4_000_000
MAX_BUNDLE_PART_BYTES = 500_000
MAX_BUNDLE_PARTS = 16
MAX_MEMBER_BYTES = 2_097_152
MAX_EXPANDED_BYTES = 8_388_608
MAX_ARCHIVE_MEMBERS = 1025
ALLOWED_SRE_BUNDLE_ROOTS = frozenset({"kubernetes-sre", "openshift-llm-deploy"})
REQUIRED_SRE_BUNDLE_FILES = frozenset(
    {
        "kubernetes-sre/SKILL.md",
        "openshift-llm-deploy/SKILL.md",
    }
)
EXCLUDED_SRE_BUNDLE_PREFIXES: tuple[str, ...] = ()


def checked_directory(path: Path) -> None:
    if path.is_symlink():
        raise SystemExit(f"refusing symlinked state path: {path}")
    path.mkdir(mode=DIRECTORY_MODE, parents=True, exist_ok=True)
    path.chmod(DIRECTORY_MODE)


def checked_mount_root(path: Path) -> None:
    """Validate the CSI-owned mount root without changing its ownership or mode."""
    if path.is_symlink() or not path.is_dir():
        raise SystemExit(f"invalid state mount root: {path}")
    if not os.access(path, os.W_OK | os.X_OK):
        raise SystemExit(f"state mount root is not writable: {path}")


def existing_owner() -> dict[str, object] | None:
    if MARKER.is_symlink():
        raise SystemExit("invalid chart ownership marker")
    if not MARKER.exists():
        return None
    if not MARKER.is_file():
        raise SystemExit("invalid chart ownership marker")
    data = json.loads(MARKER.read_text(encoding="utf-8"))
    if data.get("schema") != 1 or data.get("release") != RELEASE:
        raise SystemExit("PVC is owned by another Helm release")
    if data.get("status", "ready") not in {"seeding", "ready"}:
        raise SystemExit("invalid chart ownership marker status")
    return data


def atomic_write(destination: Path, payload: bytes, mode: int) -> None:
    """Replace one regular file without following an attacker-controlled temp link."""
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.chmod(mode)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def write_owner_marker(status: str = "ready") -> None:
    if status not in {"seeding", "ready"}:
        raise ValueError("invalid ownership marker status")
    payload = (
        json.dumps(
            {
                "schema": 1,
                "release": RELEASE,
                "revision": RELEASE_REVISION,
                "status": status,
            },
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    atomic_write(MARKER, payload, 0o644)


def claim_state_for_reconciliation() -> None:
    """Establish retry-safe ownership without adopting pre-existing content."""
    if existing_owner() is None:
        managed_paths = (
            *(STATE / "hermes" / "skills" / name for name in ALLOWED_SRE_BUNDLE_ROOTS),
            *(STATE / "hermes" / "skills" / name for name in ("devops", "infrastructure")),
            STATE / "hermes" / "bin",
            PROXY_TOKEN_DESTINATION,
            SRE_KUBECONFIG_DESTINATION,
            MODEL_DELETE_KUBECONFIG_DESTINATION,
            METRICS_KUBECONFIG_DESTINATION,
        )
        occupied = next((path for path in managed_paths if path.exists() or path.is_symlink()), None)
        if occupied is not None:
            raise SystemExit(f"refusing to replace unowned chart path: {occupied}")
    # A pending marker lets the same release recover after any later mutation,
    # while wait_seed.py refuses to treat this revision as complete.
    write_owner_marker("seeding")


def safe_member_name(name: str) -> bool:
    relative = PurePosixPath(name)
    return bool(
        name
        and not relative.is_absolute()
        and ".." not in relative.parts
        and "." not in relative.parts
        and "\\" not in name
        and "\x00" not in name
    )


def allowed_sre_bundle_member(name: str) -> bool:
    relative = PurePosixPath(name)
    return bool(
        safe_member_name(name)
        and relative.parts
        and relative.parts[0] in ALLOWED_SRE_BUNDLE_ROOTS
        and not any(part.startswith(".") or part == "__pycache__" for part in relative.parts)
        and not name.endswith(".pyc")
        and not name.startswith(EXCLUDED_SRE_BUNDLE_PREFIXES)
    )


def load_sre_bundle_parts(bundle_root: Path, expected_parts_json: str) -> bytes:
    """Reassemble the exact chart-declared ConfigMap chunks in memory."""
    try:
        definition = json.loads(expected_parts_json)
    except json.JSONDecodeError as error:
        raise SystemExit("invalid SRE bundle parts definition") from error
    if not isinstance(definition, dict) or set(definition) != {"parts", "version"}:
        raise SystemExit("invalid SRE bundle parts definition")
    parts = definition.get("parts")
    if definition.get("version") != 1 or not isinstance(parts, list):
        raise SystemExit("invalid SRE bundle parts definition")
    if not 1 <= len(parts) <= MAX_BUNDLE_PARTS:
        raise SystemExit("invalid SRE bundle part count")
    try:
        mount_root = bundle_root.resolve(strict=True)
    except OSError as error:
        raise SystemExit("invalid SRE bundle mount") from error
    if not mount_root.is_dir():
        raise SystemExit("invalid SRE bundle mount")
    expected_names: set[str] = set()
    archive = bytearray()
    for index, part in enumerate(parts):
        if not isinstance(part, dict) or set(part) != {"name", "sha256", "size"}:
            raise SystemExit("invalid SRE bundle parts definition")
        name = part.get("name")
        digest = part.get("sha256")
        size = part.get("size")
        if (
            name != f"sre-skills.part-{index:03d}"
            or not isinstance(digest, str)
            or not re.fullmatch(r"[a-f0-9]{64}", digest)
            or isinstance(size, bool)
            or not isinstance(size, int)
            or not 1 <= size <= MAX_BUNDLE_PART_BYTES
            or name in expected_names
        ):
            raise SystemExit("invalid SRE bundle parts definition")
        expected_names.add(name)
        part_path = bundle_root / name
        try:
            resolved_part = part_path.resolve(strict=True)
        except OSError as error:
            raise SystemExit(f"invalid SRE bundle part: {name}") from error
        if not resolved_part.is_file() or not resolved_part.is_relative_to(mount_root):
            raise SystemExit(f"invalid SRE bundle part: {name}")
        payload = resolved_part.read_bytes()
        if len(payload) != size or hashlib.sha256(payload).hexdigest() != digest:
            raise SystemExit(f"SRE bundle part SHA-256 mismatch: {name}")
        archive.extend(payload)
        if len(archive) > MAX_ARCHIVE_BYTES:
            raise SystemExit("SRE archive exceeds the configured size limit")
    visible_names = {
        path.name for path in bundle_root.iterdir() if not path.name.startswith(".")
    }
    if visible_names != expected_names:
        raise SystemExit("unexpected files in SRE bundle mount")
    return bytes(archive)


def load_sre_bundle(
    bundle_root: Path,
    expected_digest: str,
    expected_manifest_digest: str,
    expected_parts_json: str,
) -> dict[str, bytes]:
    """Verify and load the reviewed archive without extracting it."""
    if not re.fullmatch(r"[a-f0-9]{64}", expected_digest) or not re.fullmatch(
        r"[a-f0-9]{64}", expected_manifest_digest
    ):
        raise SystemExit("invalid expected SRE bundle SHA-256")
    archive_bytes = load_sre_bundle_parts(bundle_root, expected_parts_json)
    if not archive_bytes or len(archive_bytes) > MAX_ARCHIVE_BYTES:
        raise SystemExit("SRE archive exceeds the configured size limit")
    if hashlib.sha256(archive_bytes).hexdigest() != expected_digest:
        raise SystemExit("SRE archive SHA-256 mismatch")

    payloads: dict[str, bytes] = {}
    expanded = 0
    try:
        with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:xz") as archive:
            members = archive.getmembers()
            if not members or len(members) > MAX_ARCHIVE_MEMBERS:
                raise SystemExit("SRE archive contains an invalid number of members")
            for member in members:
                if (
                    not safe_member_name(member.name)
                    or not member.isfile()
                    or member.size < 0
                    or member.size > MAX_MEMBER_BYTES
                ):
                    raise SystemExit(f"unsafe archive member: {member.name}")
                if (
                    member.name != "MANIFEST.sha256"
                    and not allowed_sre_bundle_member(member.name)
                ):
                    raise SystemExit(f"unexpected files in SRE archive: {member.name}")
                if member.name in payloads:
                    raise SystemExit(f"unexpected files in SRE archive: {member.name}")
                expanded += member.size
                if expanded > MAX_EXPANDED_BYTES:
                    raise SystemExit("SRE archive expanded size exceeds the configured limit")
                stream = archive.extractfile(member)
                if stream is None:
                    raise SystemExit(f"unreadable archive member: {member.name}")
                payload = stream.read(MAX_MEMBER_BYTES + 1)
                if len(payload) != member.size:
                    raise SystemExit(f"truncated archive member: {member.name}")
                if member.name != "MANIFEST.sha256":
                    if not payload or b"\x00" in payload:
                        raise SystemExit(f"invalid skill payload: {member.name}")
                    try:
                        payload.decode("utf-8")
                    except UnicodeDecodeError as error:
                        raise SystemExit(f"invalid skill payload: {member.name}") from error
                payloads[member.name] = payload
    except (tarfile.TarError, OSError) as error:
        raise SystemExit("invalid SRE archive") from error

    if "MANIFEST.sha256" not in payloads:
        raise SystemExit("SRE archive manifest is missing")
    manifest_payload = payloads.pop("MANIFEST.sha256")
    if hashlib.sha256(manifest_payload).hexdigest() != expected_manifest_digest:
        raise SystemExit("SRE archive manifest SHA-256 mismatch")
    try:
        manifest_lines = manifest_payload.decode("utf-8").splitlines()
    except UnicodeError as error:
        raise SystemExit("invalid SRE archive manifest") from error
    manifest: dict[str, str] = {}
    for line in manifest_lines:
        digest, separator, name = line.partition("  ")
        if (
            separator != "  "
            or not re.fullmatch(r"[a-f0-9]{64}", digest)
            or not allowed_sre_bundle_member(name)
            or name in manifest
        ):
            raise SystemExit("invalid SRE archive manifest")
        manifest[name] = digest
    if set(manifest) != set(payloads):
        raise SystemExit("invalid SRE archive manifest")
    missing = REQUIRED_SRE_BUNDLE_FILES - set(manifest)
    if missing:
        raise SystemExit("SRE archive is missing required skill files")
    for name, payload in payloads.items():
        if hashlib.sha256(payload).hexdigest() != manifest[name]:
            raise SystemExit(f"manifest SHA-256 mismatch: {name}")
    return payloads


def model_configuration_payloads() -> dict[str, bytes]:
    """Render non-secret chart values beside the immutable model skill."""
    try:
        defaults = json.loads(os.environ["DYNAMO_DEFAULTS_JSON"])
        intake = json.loads(os.environ["HF_TOKEN_INTAKE_JSON"])
    except (KeyError, json.JSONDecodeError) as error:
        raise SystemExit("invalid model skill configuration") from error
    required_defaults = (
        "enabled",
        "apiVersion",
        "vllmRuntimeImage",
        "vllmRuntimeVersion",
        "tensorrtllmRuntimeImage",
        "tensorrtllmRuntimeVersion",
        "standardVllmImage",
        "modelRuntimeOverrides",
        "observationTimeoutSeconds",
        "downloadObservationTimeoutSeconds",
        "downloadTimeoutSeconds",
        "verificationTimeoutSeconds",
        "terminalTimeoutSeconds",
        "imagePullSecretName",
    )
    if any(key not in defaults for key in required_defaults):
        raise SystemExit("incomplete Dynamo defaults")
    if not isinstance(defaults["modelRuntimeOverrides"], dict):
        raise SystemExit("invalid model runtime overrides")

    lines = [
        f"{key}: {json.dumps(defaults[key], separators=(',', ':'))}"
        for key in required_defaults
        if key != "modelRuntimeOverrides"
    ]
    lines.append("modelRuntimeOverrides:")
    for model, override in sorted(defaults["modelRuntimeOverrides"].items()):
        if not isinstance(model, str) or not model or not isinstance(override, dict):
            raise SystemExit("invalid model runtime override")
        lines.append(f"  {json.dumps(model)}:")
        for key, value in sorted(override.items()):
            lines.append(f"    {key}: {json.dumps(value, separators=(',', ':'))}")
    defaults_yaml = ("\n".join(lines) + "\n").encode("utf-8")

    required_intake = (
        "enabled",
        "namespace",
        "secretName",
        "secretKey",
        "deleteAfterDownload",
        "requireTokenForHuggingFaceModels",
        "modelRunnerServiceAccount",
    )
    if any(key not in intake for key in required_intake):
        raise SystemExit("incomplete Hugging Face Secret reference")
    intake_yaml = (
        "\n".join(
            f"{key}: {json.dumps(intake[key], separators=(',', ':'))}"
            for key in required_intake
        )
        + "\n"
    ).encode("utf-8")
    return {
        "openshift-llm-deploy/dynamo-defaults.yaml": defaults_yaml,
        "openshift-llm-deploy/hf-token-intake.yaml": intake_yaml,
    }


def replace_owned_directory(staged: Path | None, destination: Path) -> None:
    owner = existing_owner()
    if destination.is_symlink():
        raise SystemExit(f"invalid chart-owned directory: {destination}")
    if destination.exists() and owner is None:
        raise SystemExit(f"refusing to replace unowned chart directory: {destination}")
    if destination.exists() and not destination.is_dir():
        raise SystemExit(f"invalid chart-owned directory: {destination}")
    if staged is None:
        if destination.exists():
            set_directory_tree_mode(destination, 0o700)
            shutil.rmtree(destination)
        return
    backup = destination.with_name(f".{destination.name}.previous-{os.getpid()}")
    if backup.exists():
        raise SystemExit(f"unexpected chart backup path: {backup}")
    if destination.exists():
        os.replace(destination, backup)
    try:
        os.replace(staged, destination)
    except Exception:
        if backup.exists() and not destination.exists():
            os.replace(backup, destination)
        raise
    if backup.exists():
        set_directory_tree_mode(backup, 0o700)
        shutil.rmtree(backup)


def set_directory_tree_mode(root: Path, mode: int) -> None:
    """Set only directory modes for a verified chart-owned tree."""
    if root.is_symlink() or not root.is_dir():
        raise SystemExit(f"invalid chart-owned directory tree: {root}")
    directories = [root]
    for path in root.rglob("*"):
        if path.is_symlink():
            raise SystemExit(f"unexpected symlink in chart-owned directory tree: {path}")
        if path.is_dir():
            directories.append(path)
    for directory in sorted(directories, key=lambda path: len(path.parts), reverse=True):
        directory.chmod(mode)


def reconcile_sre_skills(
    enabled: bool,
    model_skill_enabled: bool,
    payloads: dict[str, bytes] | None,
) -> None:
    skills_root = STATE / "hermes" / "skills"
    if not enabled:
        for skill in (
            "devops",
            "infrastructure",
            "kubernetes-sre",
            "openshift-llm-deploy",
        ):
            replace_owned_directory(None, skills_root / skill)
        return
    if payloads is None:
        raise SystemExit("SRE bundle payloads are required when SRE is enabled")

    install_payloads = dict(payloads)
    if model_skill_enabled:
        install_payloads.update(model_configuration_payloads())
    staging = Path(tempfile.mkdtemp(prefix=".sre-skills-", dir=STATE / "hermes"))
    try:
        for name, payload in install_payloads.items():
            target = staging / Path(*PurePosixPath(name).parts)
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            target.write_bytes(payload)
            target.chmod(0o555 if "/scripts/" in f"/{name}" else 0o444)
        # Remove skill trees shipped by pre-merge chart revisions. They are no
        # longer part of the reviewed bundle and must not survive an upgrade.
        for legacy_skill in ("devops", "infrastructure"):
            replace_owned_directory(None, skills_root / legacy_skill)
        destinations = {"kubernetes-sre": skills_root / "kubernetes-sre"}
        model_destination = skills_root / "openshift-llm-deploy"
        for name, destination in destinations.items():
            replace_owned_directory(staging / name, destination)
        replace_owned_directory(
            staging / "openshift-llm-deploy" if model_skill_enabled else None,
            model_destination,
        )
        for destination in destinations.values():
            set_directory_tree_mode(destination, 0o555)
        if model_skill_enabled:
            set_directory_tree_mode(model_destination, 0o555)
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def reconcile_proxy_token(enabled: bool) -> str | None:
    """Copy the proxy credential into chart-owned state without exposing it in a pod spec."""
    owner = existing_owner()
    if PROXY_TOKEN_DESTINATION.is_symlink():
        raise SystemExit(f"invalid chart-owned proxy token path: {PROXY_TOKEN_DESTINATION}")
    if PROXY_TOKEN_DESTINATION.exists():
        if owner is None:
            raise SystemExit(f"refusing to replace unowned proxy token: {PROXY_TOKEN_DESTINATION}")
        if not PROXY_TOKEN_DESTINATION.is_file():
            raise SystemExit(f"invalid chart-owned proxy token path: {PROXY_TOKEN_DESTINATION}")
    if not enabled:
        PROXY_TOKEN_DESTINATION.unlink(missing_ok=True)
        return None
    if not PROXY_TOKEN_SOURCE.is_file():
        raise SystemExit("invalid SRE proxy token source")
    token = PROXY_TOKEN_SOURCE.read_bytes()
    if not token or len(token) > 4096:
        raise SystemExit("invalid SRE proxy token length")
    try:
        token_text = token.decode("ascii")
    except UnicodeDecodeError as error:
        raise SystemExit("invalid SRE proxy token encoding") from error
    if re.fullmatch(r"[\x21-\x7e]+", token_text) is None:
        raise SystemExit("invalid SRE proxy token characters")
    atomic_write(PROXY_TOKEN_DESTINATION, token, PROXY_TOKEN_MODE)
    return token_text


def load_proxy_ca(enabled: bool) -> bytes | None:
    """Load and validate only the public CA from its read-only Secret projection."""
    if not enabled:
        return None
    try:
        mount_root = PROXY_CA_SOURCE.parent.resolve(strict=True)
        resolved_ca = PROXY_CA_SOURCE.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise SystemExit("invalid SRE proxy CA source") from error
    if not resolved_ca.is_file() or not resolved_ca.is_relative_to(mount_root):
        raise SystemExit("invalid SRE proxy CA source")
    certificate_authority = resolved_ca.read_bytes()
    if not certificate_authority or len(certificate_authority) > 65536:
        raise SystemExit("invalid SRE proxy CA length")
    try:
        ca_text = certificate_authority.decode("ascii")
        context = ssl.create_default_context()
        context.load_verify_locations(cadata=ca_text)
    except (UnicodeError, ssl.SSLError, ValueError) as error:
        raise SystemExit("invalid SRE proxy CA certificate") from error
    return certificate_authority


def reconcile_cli(enabled: bool) -> None:
    destination = STATE / "hermes" / "bin"
    if not enabled:
        replace_owned_directory(None, destination)
        return
    staging = Path(tempfile.mkdtemp(prefix=".sre-cli-", dir=STATE / "hermes"))
    try:
        for name in ("oc", "kubectl"):
            source = CLI_SOURCE / name
            if source.is_symlink() or not source.is_file() or not os.access(source, os.X_OK):
                raise SystemExit(f"invalid staged SRE CLI: {name}")
            target = staging / name
            shutil.copyfile(source, target)
            target.chmod(0o555)
        staging.chmod(0o555)
        replace_owned_directory(staging, destination)
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def checked_proxy_endpoint(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.username
        or parsed.password
        or parsed.path
        or parsed.query
        or parsed.fragment
        or not parsed.hostname
        or not parsed.hostname.endswith(".svc.cluster.local")
        or parsed.port is None
        or not 1024 <= parsed.port <= 65535
    ):
        raise SystemExit("invalid SRE proxy endpoint")
    return value


def write_kubeconfig(
    destination: Path,
    server: str,
    namespace: str,
    token: str,
    certificate_authority: bytes,
) -> None:
    server = checked_proxy_endpoint(server)
    if not re.fullmatch(r"[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?", namespace):
        raise SystemExit("invalid SRE kubeconfig namespace")
    if re.fullmatch(r"[\x21-\x7e]{1,4096}", token) is None:
        raise SystemExit("invalid SRE kubeconfig token")
    if not certificate_authority or len(certificate_authority) > 65536:
        raise SystemExit("invalid SRE proxy certificate authority")
    encoded_ca = base64.b64encode(certificate_authority).decode("ascii")
    content = (
        "apiVersion: v1\n"
        "kind: Config\n"
        "clusters:\n"
        "- name: chart-proxy\n"
        "  cluster:\n"
        f"    server: {json.dumps(server)}\n"
        f"    certificate-authority-data: {encoded_ca}\n"
        "users:\n"
        "- name: chart-proxy\n"
        "  user:\n"
        f"    token: {json.dumps(token)}\n"
        "contexts:\n"
        "- name: chart-proxy\n"
        "  context:\n"
        "    cluster: chart-proxy\n"
        "    user: chart-proxy\n"
        f"    namespace: {json.dumps(namespace)}\n"
        "current-context: chart-proxy\n"
    )
    if destination.is_symlink():
        raise SystemExit(f"invalid chart-owned kubeconfig: {destination}")
    if destination.exists():
        if existing_owner() is None:
            raise SystemExit(f"refusing to replace unowned kubeconfig: {destination}")
        if not destination.is_file():
            raise SystemExit(f"invalid chart-owned kubeconfig: {destination}")
    atomic_write(destination, content.encode("utf-8"), 0o600)


def reconcile_kubeconfigs(
    enabled: bool,
    model_delete_enabled: bool,
    metrics_enabled: bool,
    proxy_token: str | None,
    proxy_ca: bytes | None,
) -> None:
    if not enabled:
        for path in (
            SRE_KUBECONFIG_DESTINATION,
            MODEL_DELETE_KUBECONFIG_DESTINATION,
            METRICS_KUBECONFIG_DESTINATION,
        ):
            if path.exists() and existing_owner() is None:
                raise SystemExit(f"refusing to remove unowned kubeconfig: {path}")
            path.unlink(missing_ok=True)
        return
    if proxy_token is None or proxy_ca is None:
        raise SystemExit("missing runtime SRE proxy credentials")
    namespace = os.environ["RELEASE_NAMESPACE"]
    write_kubeconfig(
        SRE_KUBECONFIG_DESTINATION,
        os.environ["SRE_PROXY_ENDPOINT"],
        namespace,
        proxy_token,
        proxy_ca,
    )
    if model_delete_enabled:
        write_kubeconfig(
            MODEL_DELETE_KUBECONFIG_DESTINATION,
            os.environ["MODEL_DELETE_PROXY_ENDPOINT"],
            os.environ["MODEL_DELETE_NAMESPACE"],
            proxy_token,
            proxy_ca,
        )
    else:
        if MODEL_DELETE_KUBECONFIG_DESTINATION.exists() and existing_owner() is None:
            raise SystemExit(
                f"refusing to remove unowned kubeconfig: {MODEL_DELETE_KUBECONFIG_DESTINATION}"
            )
        MODEL_DELETE_KUBECONFIG_DESTINATION.unlink(missing_ok=True)
    if metrics_enabled:
        write_kubeconfig(
            METRICS_KUBECONFIG_DESTINATION,
            os.environ["METRICS_PROXY_ENDPOINT"],
            os.environ["METRICS_NAMESPACE"],
            proxy_token,
            proxy_ca,
        )
    else:
        if METRICS_KUBECONFIG_DESTINATION.exists() and existing_owner() is None:
            raise SystemExit(
                f"refusing to remove unowned kubeconfig: {METRICS_KUBECONFIG_DESTINATION}"
            )
        METRICS_KUBECONFIG_DESTINATION.unlink(missing_ok=True)


def main() -> None:
    checked_mount_root(STATE)
    checked_directory(STATE / "hermes")
    checked_directory(STATE / "hermes" / "skills")
    checked_directory(STATE / "workspace")
    claim_state_for_reconciliation()
    sre_enabled = os.environ.get("SRE_ENABLED") == "true"
    model_skill_enabled = os.environ.get("OPENSHIFT_LLM_DEPLOY_ENABLED") == "true"
    model_delete_enabled = os.environ.get("MODEL_DELETE_ENABLED") == "true"
    metrics_enabled = os.environ.get("METRICS_ENABLED") == "true"
    payloads = None
    if sre_enabled:
        payloads = load_sre_bundle(
            BUNDLE_SOURCE,
            os.environ["SRE_BUNDLE_SHA256"],
            os.environ["SRE_BUNDLE_MANIFEST_SHA256"],
            os.environ["SRE_BUNDLE_PARTS_JSON"],
        )
    reconcile_sre_skills(sre_enabled, model_skill_enabled, payloads)
    reconcile_cli(sre_enabled)
    proxy_token = reconcile_proxy_token(sre_enabled)
    proxy_ca = load_proxy_ca(sre_enabled)
    reconcile_kubeconfigs(
        sre_enabled,
        model_delete_enabled,
        metrics_enabled,
        proxy_token,
        proxy_ca,
    )
    write_owner_marker("ready")
    print("seeded chart-owned Hermes state")


if __name__ == "__main__":
    main()
