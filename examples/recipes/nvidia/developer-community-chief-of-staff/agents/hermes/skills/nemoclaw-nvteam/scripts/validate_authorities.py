#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Validate a NemoClaw NVTeam authority registry."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any


PERSONAS = {
    "akira",
    "alex",
    "jordan",
    "morgan",
    "parker",
    "quinn",
    "river",
    "robin",
}
IDENTITY_FIELDS = (
    "display_names",
    "nvidia_logins",
    "emails",
    "slack_user_ids",
    "github_logins",
)
SCOPE_FIELDS = ("products", "topics", "claim_types")
STABLE_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
ISO_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")


class DuplicateKeyError(ValueError):
    """Report a repeated key while decoding a JSON object."""

    def __init__(self, key: str) -> None:
        super().__init__(key)
        self.key = key


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError(key)
        result[key] = value
    return result


def _unknown_keys(
    value: dict[str, Any], allowed: set[str], path: str, errors: list[str]
) -> None:
    for key in sorted(set(value) - allowed):
        errors.append(f"{path}.{key}: unknown field")


def _required_keys(
    value: dict[str, Any], required: set[str], path: str, errors: list[str]
) -> None:
    for key in sorted(required - set(value)):
        errors.append(f"{path}.{key}: required field is missing")


def _nonempty_string(value: Any, path: str, errors: list[str]) -> bool:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{path}: expected a non-empty string")
        return False
    return True


def _stable_id(value: Any, path: str, errors: list[str]) -> bool:
    if not isinstance(value, str) or STABLE_ID.fullmatch(value) is None:
        errors.append(f"{path}: expected a lowercase hyphenated stable identifier")
        return False
    return True


def _string_set(value: Any, path: str, errors: list[str]) -> list[str] | None:
    if not isinstance(value, list):
        errors.append(f"{path}: expected an array")
        return None

    result: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        item_path = f"{path}[{index}]"
        if not _nonempty_string(item, item_path, errors):
            continue
        if item in seen:
            errors.append(f"{item_path}: duplicate exact value {item!r}")
        else:
            seen.add(item)
            result.append(item)
    return result


def _parse_date(value: Any, path: str, errors: list[str]) -> date | None:
    if not isinstance(value, str) or ISO_DATE.fullmatch(value) is None:
        errors.append(f"{path}: expected a date in exact YYYY-MM-DD form")
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        errors.append(f"{path}: expected a valid calendar date in YYYY-MM-DD form")
        return None


def _validate_people(
    people: Any,
    today: date,
    errors: list[str],
    warnings: list[str],
) -> set[str]:
    if not isinstance(people, dict):
        errors.append("$.people: expected an object")
        return set()

    person_ids: set[str] = set()
    identity_owners: dict[tuple[str, str], str] = {}
    required = {
        "display_name",
        "role_snapshot",
        "designation_basis",
        "verified_on",
        "review_after_days",
        "identities",
    }

    for person_id, person in people.items():
        id_path = f"$.people.{person_id}"
        if _stable_id(person_id, id_path, errors):
            person_ids.add(person_id)
        if not isinstance(person, dict):
            errors.append(f"{id_path}: expected an object")
            continue

        _unknown_keys(person, required, id_path, errors)
        _required_keys(person, required, id_path, errors)
        for field in ("display_name", "role_snapshot", "designation_basis"):
            if field in person:
                _nonempty_string(person[field], f"{id_path}.{field}", errors)

        verified = None
        if "verified_on" in person:
            verified = _parse_date(person["verified_on"], f"{id_path}.verified_on", errors)
            if verified is not None and verified > today:
                errors.append(
                    f"{id_path}.verified_on: date must not be later than "
                    f"{today.isoformat()}"
                )

        review_days = person.get("review_after_days")
        if isinstance(review_days, bool) or not isinstance(review_days, int) or review_days < 1:
            errors.append(f"{id_path}.review_after_days: expected an integer greater than zero")
        elif (
            verified is not None
            and verified <= today
            and (today - verified).days > review_days
        ):
            warnings.append(
                f"{id_path}: stale metadata; verified_on={verified.isoformat()} "
                f"review_after_days={review_days}"
            )

        identities = person.get("identities")
        if not isinstance(identities, dict):
            errors.append(f"{id_path}.identities: expected an object")
            continue
        identity_fields = set(IDENTITY_FIELDS)
        _unknown_keys(identities, identity_fields, f"{id_path}.identities", errors)
        _required_keys(identities, identity_fields, f"{id_path}.identities", errors)

        identity_count = 0
        for field in IDENTITY_FIELDS:
            if field not in identities:
                continue
            values = _string_set(identities[field], f"{id_path}.identities.{field}", errors)
            if values is None:
                continue
            identity_count += len(values)
            for value in values:
                identity_key = (field, value)
                previous_owner = identity_owners.get(identity_key)
                if previous_owner is not None and previous_owner != person_id:
                    errors.append(
                        f"{id_path}.identities.{field}: exact identity {value!r} "
                        f"is already assigned to {previous_owner!r}"
                    )
                else:
                    identity_owners[identity_key] = person_id
        if identity_count == 0:
            errors.append(f"{id_path}.identities: at least one exact identity is required")

    return person_ids


def _validate_assignments(
    assignments: Any, person_ids: set[str], errors: list[str]
) -> None:
    if not isinstance(assignments, dict):
        errors.append("$.assignments: expected an object")
        return

    required = {"person_id", "persona", "level", "enabled", "scope", "rationale"}
    for assignment_id, assignment in assignments.items():
        id_path = f"$.assignments.{assignment_id}"
        _stable_id(assignment_id, id_path, errors)
        if not isinstance(assignment, dict):
            errors.append(f"{id_path}: expected an object")
            continue

        _unknown_keys(assignment, required, id_path, errors)
        _required_keys(assignment, required, id_path, errors)

        person_id = assignment.get("person_id")
        if _stable_id(person_id, f"{id_path}.person_id", errors) and person_id not in person_ids:
            errors.append(f"{id_path}.person_id: unknown person reference {person_id!r}")

        persona = assignment.get("persona")
        if not isinstance(persona, str) or persona not in PERSONAS:
            errors.append(
                f"{id_path}.persona: expected one of {', '.join(sorted(PERSONAS))}"
            )

        level = assignment.get("level")
        if not isinstance(level, str) or level not in {"primary", "supporting"}:
            errors.append(f"{id_path}.level: expected 'primary' or 'supporting'")
        if not isinstance(assignment.get("enabled"), bool):
            errors.append(f"{id_path}.enabled: expected a boolean")
        if "rationale" in assignment:
            _nonempty_string(assignment["rationale"], f"{id_path}.rationale", errors)

        scope = assignment.get("scope")
        if not isinstance(scope, dict):
            errors.append(f"{id_path}.scope: expected an object")
            continue
        scope_fields = set(SCOPE_FIELDS)
        _unknown_keys(scope, scope_fields, f"{id_path}.scope", errors)
        _required_keys(scope, scope_fields, f"{id_path}.scope", errors)
        for field in SCOPE_FIELDS:
            if field in scope:
                _string_set(scope[field], f"{id_path}.scope.{field}", errors)


def validate_registry(data: Any, today: date) -> tuple[list[str], list[str]]:
    """Return structural errors and freshness warnings for a decoded registry."""

    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(data, dict):
        return ["$: expected a JSON object"], warnings

    allowed = {"$schema", "schema_version", "registry_kind", "people", "assignments"}
    required = {"schema_version", "registry_kind", "people", "assignments"}
    _unknown_keys(data, allowed, "$", errors)
    _required_keys(data, required, "$", errors)

    if "$schema" in data:
        _nonempty_string(data["$schema"], "$.$schema", errors)
    schema_version = data.get("schema_version")
    if (
        isinstance(schema_version, bool)
        or not isinstance(schema_version, int)
        or schema_version != 1
    ):
        errors.append("$.schema_version: expected the integer 1")
    if data.get("registry_kind") != "base":
        errors.append("$.registry_kind: expected 'base'")

    person_ids = _validate_people(data.get("people"), today, errors, warnings)
    _validate_assignments(data.get("assignments"), person_ids, errors)
    return errors, warnings


def _argument_date(value: str) -> date:
    if ISO_DATE.fullmatch(value) is None:
        raise argparse.ArgumentTypeError("expected a date in exact YYYY-MM-DD form")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "expected a valid calendar date in YYYY-MM-DD form"
        ) from exc


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("registry", type=Path, help="Path to persona-authorities.json")
    parser.add_argument(
        "--today",
        type=_argument_date,
        default=date.today(),
        metavar="YYYY-MM-DD",
        help="Date used for deterministic freshness checks",
    )
    parser.add_argument(
        "--fail-on-stale",
        action="store_true",
        help="Treat stale registry metadata as a validation failure",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable output")
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    errors: list[str] = []
    warnings: list[str] = []

    try:
        data = json.loads(
            args.registry.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except OSError as exc:
        errors.append(f"$: unable to read registry: {exc}")
    except DuplicateKeyError as exc:
        errors.append(f"$: duplicate JSON object key {exc.key!r}")
    except json.JSONDecodeError as exc:
        errors.append(f"$: invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}")
    except ValueError as exc:
        errors.append(f"$: invalid JSON value: {exc}")
    else:
        errors, warnings = validate_registry(data, args.today)

    if args.fail_on_stale and warnings:
        errors.extend(f"strict freshness: {warning}" for warning in warnings)

    valid = not errors
    if args.json:
        print(
            json.dumps(
                {
                    "valid": valid,
                    "registry": str(args.registry),
                    "errors": errors,
                    "warnings": warnings,
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        for warning in warnings:
            print(f"warning: {warning}", file=sys.stderr)
        if valid:
            print(f"valid: {args.registry}")
        else:
            print(f"invalid: {args.registry}", file=sys.stderr)
            for error in errors:
                print(f"error: {error}", file=sys.stderr)
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
