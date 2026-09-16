#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Confirm README runtime-stack declarations from a few standard code shapes."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from functools import cache
from pathlib import Path


_SPECIAL_VALUES = {"N/A", "Unknown", "Unpinned"}
_HARNESS_NAMES = (
    "LangChain Deep Agents Code",
    "LangChain Deep Agents",
    "OpenClaw",
    "Hermes",
)
_HARNESS_COMPONENTS = {
    "Hermes": "hermes",
    "OpenClaw": "openclaw",
    "LangChain Deep Agents": "deepagents",
    "LangChain Deep Agents Code": "langchain-code",
}
_COMPONENT_HARNESSES = {component: name for name, component in _HARNESS_COMPONENTS.items()}
_AGENT_HARNESSES = {
    "hermes": "Hermes",
    "hermes-agent": "Hermes",
    "openclaw": "OpenClaw",
    "langchain-deepagents-code": "LangChain Deep Agents Code",
}
_EXACT_VERSION = re.compile(r"v?\d+(?:\.\d+){1,3}(?:[-+][0-9A-Za-z.-]+)?\Z")
_VERSION_RANGE = re.compile(
    r"(?:==|!=|<=|>=|~=|<|>|\^|~)\s*v?\d+(?:\.\d+){1,3}"
    r"(?:\s*,\s*(?:==|!=|<=|>=|~=|<|>|\^|~)\s*v?\d+(?:\.\d+){1,3})*\Z"
)
_COMMIT = re.compile(r"[0-9a-f]{40}\Z")
_DYNAMIC = re.compile(r"\$|`|\b(?:HEAD|develop|latest|main|master|nightly)\b", re.I)
_ASSIGNMENT_KEYS = {
    "nemoclaw": (
        "NEMOCLAW_VERSION",
        "NEMOCLAW_COMMIT",
        "NEMOCLAW_INSTALL_TAG",
        "NEMOCLAW_INSTALL_REF",
    ),
    "hermes": ("HERMES_VERSION", "HERMES_SEMVER"),
    "openclaw": ("OPENCLAW_VERSION",),
    "deepagents": ("DEEPAGENTS_VERSION", "DEEP_AGENTS_VERSION"),
    "langchain-code": ("LANGCHAIN_DEEP_AGENTS_CODE_VERSION",),
    "openshell": ("OPENSHELL_VERSION",),
}
_RELEASE_CONTRACT_PATH = Path(__file__).with_name("nemoclaw-release-contracts.json")


@dataclass(frozen=True, slots=True)
class StackDeclaration:
    """The three human-readable stack rows from an example README."""

    nemoclaw: str
    harness_name: str | None
    harness_version: str | None
    harness_value: str
    openshell: str


@dataclass(frozen=True, slots=True)
class ComponentFact:
    """One displayed component after static evidence and README data are merged."""

    name: str | None
    version: str | None
    status: str


@dataclass(frozen=True, slots=True)
class StackFacts:
    """Serializable stack facts and their overall verification state."""

    nemoclaw: ComponentFact
    harness: ComponentFact
    openshell: ComponentFact
    status: str
    evidence_paths: tuple[str, ...]
    reasons: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        """Return JSON-compatible primitives."""

        return asdict(self)


@dataclass(slots=True)
class _Detected:
    values: dict[str, set[str]]
    paths: dict[str, set[str]]
    harness_names: set[str]
    notes: list[str]


def _version_kind(value: str) -> str:
    if value in _SPECIAL_VALUES:
        return value.casefold().replace("/", "-")
    if _EXACT_VERSION.fullmatch(value):
        return "exact"
    if _VERSION_RANGE.fullmatch(value):
        return "range"
    return "invalid"


def _normalized_exact(value: str) -> str:
    """Return one comparison form for exact versions with an optional v prefix."""

    return value[1:] if value.startswith("v") else value


def parse_stack_declaration(
    nemoclaw: str,
    harness: str,
    openshell: str,
) -> StackDeclaration:
    """Parse the deliberately small README stack grammar."""

    if _version_kind(nemoclaw) == "invalid":
        raise ValueError("NemoClaw must be an exact/ranged version, Unpinned, Unknown, or N/A")
    if _version_kind(openshell) == "invalid":
        raise ValueError("OpenShell must be an exact/ranged version, Unpinned, Unknown, or N/A")
    if harness in _SPECIAL_VALUES:
        harness_name = None
        harness_version = None
    else:
        harness_name = next(
            (name for name in _HARNESS_NAMES if harness.startswith(name + " ")),
            None,
        )
        if harness_name is None:
            raise ValueError(
                "Harness must name Hermes, OpenClaw, LangChain Deep Agents, "
                "or LangChain Deep Agents Code"
            )
        harness_version = harness.removeprefix(harness_name + " ")
        if _version_kind(harness_version) == "invalid" or harness_version == "N/A":
            raise ValueError(
                "Harness must pair its name with an exact/ranged version, Unpinned, or Unknown"
            )
    return StackDeclaration(
        nemoclaw,
        harness_name,
        harness_version,
        harness,
        openshell,
    )


def _runtime_files(root: Path) -> list[Path]:
    """Return supported Dockerfiles; custom layouts fall back to README data."""

    candidates = list(root.glob("Dockerfile*"))
    candidates.extend(root.glob("agents/*/Dockerfile*"))
    files: list[Path] = []
    for path in sorted(set(candidates)):
        try:
            relative = path.relative_to(root)
        except ValueError:
            continue
        prefixes = (
            root.joinpath(*relative.parts[:index])
            for index in range(1, len(relative.parts) + 1)
        )
        if (
            path.is_file()
            and path.stat().st_size <= 1_000_000
            and not any(candidate.is_symlink() for candidate in prefixes)
        ):
            files.append(path)
    return files


def _active_text(path: Path) -> str:
    """Remove full-line comments without interpreting a scripting language."""

    return "\n".join(
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    )


def _assignment_values(text: str, keys: tuple[str, ...]) -> set[str]:
    key_pattern = "|".join(re.escape(key) for key in keys)
    pattern = re.compile(
        rf"\b(?:{key_pattern})\s*(?:=|:)\s*[\"']?(?P<value>[^\s\"';,]+)",
    )
    values: set[str] = set()
    for match in pattern.finditer(text):
        value = match.group("value").rstrip("}])")
        if _EXACT_VERSION.fullmatch(value) or _VERSION_RANGE.fullmatch(value) or _COMMIT.fullmatch(value):
            values.add(value)
        elif _DYNAMIC.search(value):
            values.add("Unpinned")
    return values


@cache
def _release_contracts() -> tuple[dict[str, dict[str, object]], dict[str, str]]:
    document = json.loads(_RELEASE_CONTRACT_PATH.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("NemoClaw release contracts must be an object")
    aliases: dict[str, str] = {}
    for tag, record in document.items():
        if (
            not isinstance(tag, str)
            or not re.fullmatch(r"v\d+(?:\.\d+){2}", tag)
            or not isinstance(record, dict)
        ):
            raise ValueError(f"invalid NemoClaw release contract: {tag!r}")
        expected = {"commit", "openshell", "harnesses"}
        if set(record) != expected or not _COMMIT.fullmatch(str(record["commit"])):
            raise ValueError(f"invalid NemoClaw release contract for {tag}")
        if _version_kind(str(record["openshell"])) != "exact":
            raise ValueError(f"invalid OpenShell release contract for {tag}")
        harnesses = record["harnesses"]
        if not isinstance(harnesses, dict) or not harnesses:
            raise ValueError(f"invalid harness release contract for {tag}")
        if any(
            name not in _HARNESS_NAMES or _version_kind(str(version)) != "exact"
            for name, version in harnesses.items()
        ):
            raise ValueError(f"invalid harness version in release contract for {tag}")
        aliases[tag] = tag
        aliases[tag.removeprefix("v")] = tag
        aliases[str(record["commit"])] = tag
    return document, aliases


def _scan(root: Path) -> _Detected:
    values = {key: set() for key in _ASSIGNMENT_KEYS}
    paths = {key: set() for key in values}
    harness_names: set[str] = set()
    notes: list[str] = []
    for path in _runtime_files(root):
        relative = path.relative_to(root).as_posix()
        text = _active_text(path)
        for component, keys in _ASSIGNMENT_KEYS.items():
            found = _assignment_values(text, keys)
            if found:
                values[component].update(found)
                paths[component].add(relative)
                harness_name = _COMPONENT_HARNESSES.get(component)
                if harness_name:
                    harness_names.add(harness_name)
        for agent in re.findall(r"\bNEMOCLAW_AGENT\s*=\s*[\"']?([A-Za-z-]+)", text):
            harness = _AGENT_HARNESSES.get(agent.casefold())
            if harness:
                harness_names.add(harness)
            else:
                notes.append(f"NemoClaw agent selection {agent!r} is not recognized.")

    contracts, aliases = _release_contracts()
    identities = values["nemoclaw"] - {"Unpinned"}
    releases = {aliases[value] for value in identities if value in aliases}
    unknown_identities = identities - set(aliases)
    if unknown_identities or len(releases) > 1 or (releases and "Unpinned" in values["nemoclaw"]):
        notes.append("NemoClaw evidence is unknown, mutable, or conflicting.")
    elif len(releases) == 1:
        tag = next(iter(releases))
        values["nemoclaw"] = {tag}
        contract = contracts[tag]
        if len(harness_names) == 1:
            harness_name = next(iter(harness_names))
            stock_version = contract["harnesses"].get(harness_name)  # type: ignore[union-attr]
            key = _HARNESS_COMPONENTS[harness_name]
            if stock_version and not values.get(key):
                values[key].add(str(stock_version))
                paths[key].update(paths["nemoclaw"])
                notes.append(f"{harness_name} {stock_version} is inferred from NemoClaw {tag}.")
        elif not harness_names:
            notes.append(
                f"NemoClaw {tag} is pinned, but no standard harness selection was found."
            )
        values["openshell"].add(str(contract["openshell"]))
        paths["openshell"].update(paths["nemoclaw"])
        notes.append(f"OpenShell {contract['openshell']} is inferred from NemoClaw {tag}.")
    return _Detected(values, paths, harness_names, notes)


def _merge_version(
    label: str,
    declared: str,
    detected: set[str],
    reasons: list[str],
) -> tuple[str | None, str]:
    declaration_kind = _version_kind(declared)
    exact_detected = {value for value in detected if _version_kind(value) == "exact"}
    normalized_detected = {_normalized_exact(value) for value in exact_detected}
    normalized_declared = _normalized_exact(declared)
    mutable_detected = detected - exact_detected
    if declaration_kind == "n-a":
        if detected:
            reasons.append(f"{label} is declared N/A but implementation evidence was found.")
            return None, "conflict"
        return None, "not-applicable"
    if declaration_kind == "unknown":
        if detected:
            reasons.append(f"{label} is Unknown in the README but implementation evidence was found.")
            return None, "conflict"
        reasons.append(f"{label} is not declared or detected.")
        return None, "unknown"
    if declaration_kind in {"unpinned", "range"}:
        if exact_detected and not mutable_detected:
            reasons.append(f"{label} is {declared} in the README but code contains an exact value.")
            return declared, "conflict"
        reasons.append(f"{label} is not pinned to one exact version.")
        return declared, "unpinned"
    if mutable_detected or len(normalized_detected) > 1 or (
        normalized_detected and normalized_declared not in normalized_detected
    ):
        reasons.append(
            f"{label} {declared} in the README conflicts with implementation evidence: "
            + ", ".join(sorted(detected))
            + "."
        )
        return declared, "conflict"
    if normalized_declared in normalized_detected:
        reasons.append(f"{label} {declared} is confirmed by implementation evidence.")
        return declared, "confirmed"
    reasons.append(f"{label} {declared} is declared in the README but not statically confirmed.")
    return declared, "unconfirmed"


def extract_example_stack_facts(
    example_root: str | Path,
    declaration: StackDeclaration,
) -> StackFacts:
    """Merge a README declaration with conservative, fixed-shape static evidence."""

    root = Path(example_root)
    detected = _scan(root)
    reasons = list(detected.notes)

    nemoclaw_version, nemoclaw_status = _merge_version(
        "NemoClaw", declaration.nemoclaw, detected.values["nemoclaw"], reasons
    )

    detected_harness_name = (
        next(iter(detected.harness_names)) if len(detected.harness_names) == 1 else None
    )
    harness_detected = detected.values.get(
        _HARNESS_COMPONENTS.get(declaration.harness_name or "", ""),
        set(),
    )
    if len(detected.harness_names) > 1 or (
        declaration.harness_name
        and detected_harness_name
        and declaration.harness_name != detected_harness_name
    ):
        harness_name = declaration.harness_name
        harness_version = declaration.harness_version
        harness_status = "conflict"
        reasons.append(
            "Harness declaration conflicts with detected harnesses: "
            + ", ".join(sorted(detected.harness_names))
            + "."
        )
    elif declaration.harness_value == "N/A":
        harness_name = None
        harness_version = None
        harness_status = "not-applicable" if not detected.harness_names else "conflict"
        if harness_status == "conflict":
            reasons.append("Harness is declared N/A but a harness was detected.")
    elif declaration.harness_value == "Unknown":
        harness_name = None
        harness_version = None
        harness_status = "unknown" if not detected.harness_names else "conflict"
        reasons.append("Harness name and version are not established.")
    elif declaration.harness_value == "Unpinned":
        harness_name = detected_harness_name
        harness_version = "Unpinned"
        harness_status = "unpinned"
        reasons.append("Harness is not pinned to one exact version.")
    else:
        harness_name = declaration.harness_name
        harness_version, harness_status = _merge_version(
            f"{harness_name} harness",
            declaration.harness_version or "Unknown",
            harness_detected,
            reasons,
        )
        if harness_status == "confirmed" and not detected_harness_name:
            harness_status = "unconfirmed"
        if harness_status == "unconfirmed" and detected_harness_name == harness_name:
            reasons.append(f"The {harness_name} name is detected, but its version is README-only.")

    openshell_version, openshell_status = _merge_version(
        "OpenShell", declaration.openshell, detected.values["openshell"], reasons
    )
    statuses = {nemoclaw_status, harness_status, openshell_status}
    if statuses == {"not-applicable"}:
        status = "not-applicable"
    elif "conflict" in statuses:
        status = "conflict"
    elif "unknown" in statuses:
        status = "unknown"
    elif "unpinned" in statuses:
        status = "unpinned"
    elif "unconfirmed" in statuses:
        status = "unconfirmed"
    else:
        status = "confirmed"

    evidence_paths = set().union(*detected.paths.values())
    if status == "not-applicable":
        reasons.append("This example declares no NemoClaw, harness, or OpenShell runtime.")
    elif not evidence_paths:
        reasons.append("No standardized runtime source was found; displayed values come from the README.")
    return StackFacts(
        ComponentFact("NemoClaw", nemoclaw_version, nemoclaw_status),
        ComponentFact(harness_name, harness_version, harness_status),
        ComponentFact("OpenShell", openshell_version, openshell_status),
        status,
        tuple(sorted(evidence_paths)),
        tuple(dict.fromkeys(reasons)),
    )
