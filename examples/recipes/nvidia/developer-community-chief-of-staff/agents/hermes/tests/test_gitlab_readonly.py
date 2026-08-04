# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import importlib.util
import io
import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

RECIPE_DIR = Path(__file__).resolve().parents[3]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def helper():
    return load_module(
        "gitlab_readonly",
        RECIPE_DIR
        / "agents/hermes/skills/gitlab-readonly-live/scripts/gitlab_readonly.py",
    )


def test_multiple_projects_require_explicit_selection(helper, monkeypatch):
    monkeypatch.setenv(
        "GITLAB_READONLY_PROJECTS",
        "example-team/project-one,group/subgroup/project-two",
    )

    with pytest.raises(SystemExit, match="multiple GitLab projects"):
        helper.choose_project(None)

    assert (
        helper.choose_project("GROUP/SUBGROUP/PROJECT-TWO")
        == "group/subgroup/project-two"
    )
    with pytest.raises(SystemExit, match="outside GITLAB_READONLY_PROJECTS"):
        helper.choose_project("another-team/unlisted")


def test_helper_rejects_sensitive_and_unsupported_routes(helper):
    for route in (
        "",
        ".",
        "/",
        "variables",
        "members",
        "repository/archive",
        "../issues",
    ):
        with pytest.raises(SystemExit):
            helper.clean_route(route)

    assert helper.clean_route("repository/files/docs%2Fguide.md") == (
        "repository/files/docs%2Fguide.md"
    )


def test_api_url_accepts_custom_host_and_rejects_credentials(helper, monkeypatch):
    monkeypatch.setenv("GITLAB_API_URL", "https://gitlab.example.com:8443/api/v4")
    assert helper.api_url() == "https://gitlab.example.com:8443/api/v4"

    monkeypatch.setenv("GITLAB_API_URL", "https://user:pass@example.com/api/v4")
    with pytest.raises(SystemExit, match="invalid GITLAB_API_URL"):
        helper.api_url()

    monkeypatch.setenv("GITLAB_API_URL", "http://gitlab.example.com/api/v4")
    with pytest.raises(SystemExit, match="invalid GITLAB_API_URL"):
        helper.api_url()


def test_policy_rules_are_get_only_and_project_scoped():
    stage = load_module(
        "stage_gitlab_policy",
        RECIPE_DIR / "scripts/lib/stage-gitlab-policy.py",
    )
    template = "rules:\n      __GITLAB_READONLY_RULES__\n"

    rendered = stage.render_policy(
        template,
        ["example-team/project-one=123", "group/subgroup/project-two=456"],
    )

    assert 'method: GET, path: "/api/v4/projects/123"' not in rendered
    assert 'method: GET, path: "/api/v4/projects/123/issues"' in rendered
    assert 'method: GET, path: "/api/v4/projects/456/merge_requests/**"' in rendered
    assert "POST" not in rendered
    assert "/variables" not in rendered
    assert "/members" not in rendered
    assert stage.MARKER not in rendered


def test_disabled_policy_has_no_project_or_identity_route():
    stage = load_module(
        "stage_gitlab_policy_disabled",
        RECIPE_DIR / "scripts/lib/stage-gitlab-policy.py",
    )
    template = "rules:\n      __GITLAB_READONLY_RULES__\n"

    rendered = stage.render_policy(template, [])

    assert "/api/v4/__gitlab_disabled__" in rendered
    assert "/api/v4/user" not in rendered
    assert "/api/v4/projects/" not in rendered


def test_staged_repository_policy_is_valid_yaml_and_get_only():
    stage = load_module(
        "stage_gitlab_policy_repository",
        RECIPE_DIR / "scripts/lib/stage-gitlab-policy.py",
    )
    template = (RECIPE_DIR / "policy.yaml").read_text(encoding="utf-8")

    rendered = stage.render_policy(template, ["example-team/project-one=123"])
    policy = yaml.safe_load(rendered)
    rules = policy["network_policies"]["gitlab_projects_readonly"]["endpoints"][
        0
    ]["rules"]
    allowed_ips = policy["network_policies"]["gitlab_projects_readonly"][
        "endpoints"
    ][0]["allowed_ips"]

    assert rules
    assert {rule["allow"]["method"] for rule in rules} == {"GET"}
    assert all(
        rule["allow"]["path"] == "/api/v4/user"
        or rule["allow"]["path"].startswith("/api/v4/projects/123/")
        for rule in rules
    )
    assert "/api/v4/projects/123" not in {
        rule["allow"]["path"] for rule in rules
    }
    assert "172.16.0.0/12" in allowed_ips
    assert "172.0.0.0/8" not in allowed_ips


def test_helper_blocks_cross_origin_redirects(helper):
    request = urllib.request.Request(
        "https://gitlab.example.com/api/v4/user",
        headers={"Authorization": "Bearer secret"},
    )
    handler = helper.SameOriginRedirectHandler()

    with pytest.raises(urllib.error.URLError, match="cross-origin"):
        handler.redirect_request(
            request,
            None,
            302,
            "Found",
            {},
            "https://attacker.example/collect",
        )

    redirected = handler.redirect_request(
        request,
        None,
        302,
        "Found",
        {},
        "/api/v4/users/1",
    )
    assert redirected.full_url == "https://gitlab.example.com/api/v4/users/1"


def test_helper_does_not_print_untrusted_gitlab_error_body(
    helper, monkeypatch, capsys
):
    monkeypatch.setenv("GITLAB_API_URL", "https://gitlab.example.com/api/v4")
    monkeypatch.setenv("GITLAB_TOKEN", "test-secret-token")
    error = urllib.error.HTTPError(
        "https://gitlab.example.com/api/v4/user",
        403,
        "untrusted reason",
        {},
        io.BytesIO(b"untrusted response body"),
    )

    def fail(_request, timeout):
        assert timeout == 30
        raise error

    monkeypatch.setattr(helper, "open_same_origin", fail)
    with pytest.raises(SystemExit):
        helper.get_json("/user")

    captured = capsys.readouterr()
    assert "HTTP 403" in captured.err
    assert "untrusted" not in captured.err
    assert "test-secret-token" not in captured.err


def test_project_path_maps_to_canonical_numeric_id(helper, monkeypatch):
    monkeypatch.setenv(
        "GITLAB_READONLY_PROJECT_IDS",
        "example-team/project-one=123,group/subgroup/project-two=456",
    )

    assert helper.project_id("EXAMPLE-TEAM/PROJECT-ONE") == 123


def test_limit_reports_incomplete_when_response_contains_more_items(
    helper, monkeypatch
):
    monkeypatch.setenv("GITLAB_READONLY_PROJECTS", "example-team/project-one")
    monkeypatch.setenv("GITLAB_READONLY_PROJECT_IDS", "example-team/project-one=123")
    monkeypatch.setattr(
        helper,
        "get_json",
        lambda path, params: ([{"id": 1}, {"id": 2}], {"x-next-page": ""}),
    )
    args = SimpleNamespace(
        project=None,
        route="issues",
        param=[],
        fields=None,
        paginate=False,
        count=False,
        limit=1,
    )

    result = helper.run_get(args)

    assert result == {
        "project": "example-team/project-one",
        "complete": False,
        "data": [{"id": 1}],
    }


def test_project_resolver_requires_exact_match_without_exposing_token(
    monkeypatch, capsys
):
    resolver = load_module(
        "resolve_gitlab_projects",
        RECIPE_DIR / "scripts/lib/resolve-gitlab-projects.py",
    )
    seen_requests = []

    def fake_open(request, timeout):
        assert timeout == 30
        seen_requests.append(request)
        return io.BytesIO(
            json.dumps(
                [{"id": 123, "path_with_namespace": "example-team/project-one"}]
            ).encode()
        )

    monkeypatch.setattr(resolver, "open_same_origin", fake_open)
    project, project_id = resolver.resolve_project(
        "https://gitlab.example.com/api/v4",
        "test-secret-token",
        "example-team/project-one",
    )

    assert (project, project_id) == ("example-team/project-one", 123)
    request = seen_requests[0]
    assert request.method == "GET"
    assert request.get_header("Authorization") == "Bearer test-secret-token"
    query = urllib.parse.parse_qs(urllib.parse.urlparse(request.full_url).query)
    assert query["search"] == ["example-team/project-one"]
    assert query["search_namespaces"] == ["true"]
    captured = capsys.readouterr()
    assert "test-secret-token" not in captured.out
    assert "test-secret-token" not in captured.err


def test_project_resolver_blocks_cross_origin_redirects():
    resolver = load_module(
        "resolve_gitlab_projects_redirect",
        RECIPE_DIR / "scripts/lib/resolve-gitlab-projects.py",
    )
    request = urllib.request.Request(
        "https://gitlab.example.com/api/v4/projects",
        headers={"Authorization": "Bearer secret"},
    )

    with pytest.raises(urllib.error.URLError, match="cross-origin"):
        resolver.SameOriginRedirectHandler().redirect_request(
            request,
            None,
            302,
            "Found",
            {},
            "https://attacker.example/collect",
        )
