# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Render individual example and tutorial detail pages."""

from __future__ import annotations

import html
import posixpath
import re
from pathlib import Path, PurePosixPath

from .markdown import (
    DETAIL_CONTENT_SECURITY_POLICY,
    MERMAID_SRI,
    TUTORIAL_CONTENT_SECURITY_POLICY,
    render_readme_html,
)
from .model import FEATURED_TUTORIAL_URL, CatalogEntry, CatalogError


def _detail_relative(entry: CatalogEntry, target: str) -> str:
    detail_dir = PurePosixPath(entry.detail_path).parent.as_posix()
    return posixpath.relpath(target, detail_dir)


def _display_stack_value(value: str | None, status: str) -> str:
    if status == "not-applicable":
        return "N/A"
    if value:
        return html.escape(value)
    return '<span class="fact-unknown">Unknown</span>'


def _fact_info(label: str, lines: list[str]) -> str:
    content = "".join(f"<span>{html.escape(line)}</span>" for line in lines)
    return (
        '<details class="fact-info">'
        f'<summary aria-label="{html.escape(label, quote=True)}">'
        '<span aria-hidden="true">i</span></summary>'
        f'<div class="fact-popover">{content}</div></details>'
    )


def render_stack_facts(entry: CatalogEntry) -> str:
    stack = entry.stack
    if stack is None:
        return ""
    if stack.harness.status == "not-applicable":
        harness = "N/A"
    elif stack.harness.name:
        harness = " ".join(
            (
                html.escape(stack.harness.name),
                _display_stack_value(stack.harness.version, stack.harness.status),
            )
        )
    else:
        harness = _display_stack_value(stack.harness.version, stack.harness.status)
    openshell_version = _display_stack_value(
        stack.openshell.version,
        stack.openshell.status,
    )
    status_label = {
        "confirmed": "Confirmed",
        "unconfirmed": "Unconfirmed",
        "unpinned": "Unpinned",
        "unknown": "Unknown",
        "conflict": "Conflict",
        "not-applicable": "Not applicable",
    }[stack.status]
    details = [
        re.sub(
            r" from NemoClaw v?\d+(?:\.\d+){2,3}",
            " from background release metadata",
            reason,
        )
        for reason in stack.reasons
        if not reason.startswith("NemoClaw")
    ] or ["All displayed runtime stack facts were confirmed."]
    if len(stack.evidence_paths) > 3:
        evidence = ", ".join(stack.evidence_paths[:2])
        evidence += f", and {len(stack.evidence_paths) - 2} more standardized files"
    else:
        evidence = ", ".join(stack.evidence_paths)
    details.append(
        f"Evidence: {evidence}."
        if evidence
        else "Evidence: no standardized runtime source found."
    )
    info = _fact_info("About stack metadata", details)
    status_value = (
        '<span class="status-label"><span class="status-dot" '
        f'aria-hidden="true"></span>{html.escape(status_label)}</span>'
    )
    return (
        f"<div><dt>Harness</dt><dd>{harness}</dd></div>"
        f"<div><dt>OpenShell</dt><dd>{openshell_version}</dd></div>"
        f'<div class="stack-status-fact stack-status-{stack.status}">'
        f"<dt>Stack verification</dt><dd>{status_value}{info}</dd></div>"
    )


def render_maintenance_fact(entry: CatalogEntry) -> str:
    status = entry.maintenance
    if status is None or entry.last_activity is None:
        return ""
    details = [
        status.summary,
        f"Last committed change: {entry.last_activity.isoformat()}.",
        f"Lifecycle: {entry.lifecycle}.",
        "This reflects repository activity only, not support, quality, or runtime health.",
    ]
    if entry.reviewed is not None:
        details.insert(2, f"Focused review: {entry.reviewed.isoformat()}.")
    info = _fact_info("About maintenance status", details)
    status_value = (
        '<span class="status-label"><span class="status-dot" '
        f'aria-hidden="true"></span>{html.escape(status.label)}</span>'
    )
    return (
        f'<div class="maintenance-fact maintenance-tone-{status.tone}">'
        f"<dt>Maintenance</dt><dd>{status_value}{info}</dd></div>"
    )


def render_detail_pages(
    root: Path,
    entries: list[CatalogEntry],
    template: str,
) -> tuple[dict[str, str], set[str]]:
    """Render one static, themed README page per catalog entry."""

    catalog_by_readme = {entry.readme_path: entry for entry in entries}
    copied_assets: set[str] = set()
    pages: dict[str, str] = {}
    for entry in entries:
        readme_title, readme_html, toc_html, has_mermaid = render_readme_html(
            root, entry, catalog_by_readme, copied_assets
        )
        collection_tags = "".join(
            f'\n              <li class="tag tag-collection">'
            f'{html.escape(collection.metadata_value)}</li>'
            for collection in entry.collections
        )
        if entry.contributor:
            attribution_fact = (
                f"<div><dt>Contributor</dt><dd>{html.escape(entry.contributor)}</dd></div>"
            )
        else:
            attribution_fact = ""
        upstream_fact = ""
        if entry.upstream_url:
            upstream_fact = (
                "<div><dt>Upstream project</dt><dd>"
                f'<a href="{html.escape(entry.upstream_url, quote=True)}">'
                "View upstream project <span aria-hidden=\"true\">↗</span>"
                "</a></dd></div>"
            )
        diagram_scripts = ""
        if has_mermaid:
            mermaid_url = _detail_relative(
                entry, "assets/vendor/mermaid.tiny.js"
            )
            diagrams_url = _detail_relative(entry, "scripts/diagrams.mjs")
            diagram_scripts = (
                f'    <script src="{mermaid_url}" integrity="{MERMAID_SRI}"></script>\n'
                f'    <script type="module" src="{diagrams_url}"></script>'
            )
        page_scripts = diagram_scripts
        page_styles = ""
        if entry.is_tutorial:
            page_styles = (
                f'    <link rel="stylesheet" '
                f'href="{_detail_relative(entry, "styles/tutorial.css")}">'
            )
            tutorial_script = (
                f'    <script type="module" '
                f'src="{_detail_relative(entry, "scripts/tutorial.mjs")}"></script>'
            )
            page_scripts = "\n".join(filter(None, (page_scripts, tutorial_script)))
        replacements = {
            "{{CONTENT_SECURITY_POLICY}}": html.escape(
                TUTORIAL_CONTENT_SECURITY_POLICY
                if entry.is_tutorial
                else DETAIL_CONTENT_SECURITY_POLICY,
                quote=True,
            ),
            "{{META_DESCRIPTION}}": html.escape(entry.description, quote=True),
            "{{PAGE_TITLE}}": html.escape(readme_title),
            "{{PAGE_CLASS}}": " tutorial-page" if entry.is_tutorial else "",
            "{{FAVICON_URL}}": _detail_relative(
                entry, "assets/nvidia-favicon.png"
            ),
            "{{STYLES_URL}}": _detail_relative(entry, "styles/shared.css"),
            "{{DETAIL_STYLES_URL}}": _detail_relative(
                entry, "styles/detail.css"
            ),
            "{{PAGE_STYLES}}": page_styles,
            "{{LOGO_URL}}": _detail_relative(entry, "assets/nvidia-logo.png"),
            "{{CATALOG_URL}}": _detail_relative(entry, "index.html"),
            "{{TUTORIAL_URL}}": _detail_relative(
                entry, f"{FEATURED_TUTORIAL_URL}index.html"
            ),
            "{{SOURCE_URL}}": html.escape(entry.content_url, quote=True),
            "{{DISPLAY_LABEL}}": html.escape(entry.display_label),
            "{{DESCRIPTION}}": html.escape(entry.description),
            "{{INDUSTRY}}": html.escape(entry.industry_label),
            "{{COLLECTION_TAGS}}": collection_tags,
            "{{CATEGORY}}": html.escape(entry.category.singular),
            "{{FACTS_ATTRIBUTES}}": " hidden" if entry.is_tutorial else "",
            "{{ATTRIBUTION_FACT}}": attribution_fact,
            "{{UPSTREAM_FACT}}": upstream_fact,
            "{{STACK_FACTS}}": render_stack_facts(entry),
            "{{REQUIREMENTS}}": html.escape(entry.requirements),
            "{{MAINTENANCE_FACT}}": render_maintenance_fact(entry),
            "{{TABLE_OF_CONTENTS}}": toc_html,
            "{{CONTENT_LABEL}}": "Tutorial" if entry.is_tutorial else "Example guide",
            "{{CONTENT_CLASS}}": " tutorial-content" if entry.is_tutorial else "",
            "{{README_HTML}}": readme_html,
            "{{PAGE_SCRIPTS}}": page_scripts,
        }
        rendered = template
        for marker, value in replacements.items():
            expected_counts = {
                "{{CATALOG_URL}}": 3,
                "{{INDUSTRY}}": 2,
                "{{PAGE_TITLE}}": 2,
                "{{SOURCE_URL}}": 2,
                "{{TABLE_OF_CONTENTS}}": 2,
                "{{TUTORIAL_URL}}": 2,
            }
            expected_count = expected_counts.get(marker, 1)
            if rendered.count(marker) != expected_count:
                raise CatalogError(
                    f"Expected {expected_count} {marker} marker(s) in "
                    "site/templates/detail.html."
                )
            rendered = rendered.replace(marker, value)
        leftover = re.findall(r"\{\{[A-Z0-9_]+\}\}", rendered)
        if leftover:
            raise CatalogError(
                "Unknown detail template markers: " + ", ".join(sorted(leftover))
            )
        pages[entry.detail_path] = rendered
    return pages, copied_assets
