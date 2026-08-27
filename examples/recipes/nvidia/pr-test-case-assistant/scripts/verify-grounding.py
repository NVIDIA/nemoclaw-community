#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Check whether the identifiers in an agent's answer actually exist in a pull request's diff.

An agent that drafts test cases will name types, functions, constants and fields. Those names
are the part a reader acts on, and they are also the part a language model is most likely to
manufacture: a plausible symbol can be built from a filename, and nothing in the answer marks
the difference between one that was read and one that was assembled.

This makes that difference checkable. Paste the identifiers the agent used into a file, point
this at the pull request, and every one is either present in the diff or it is not.

    ./verify-grounding.py --repo NVIDIA/NeMo-Relay --pr 783 --identifiers ids.txt

An identifiers file is one name per line. Blank lines and `#` comments are ignored. A line may
carry a category after a tab or two spaces, which only affects how results are grouped:

    NemoRelayMetricKind         type names
    boundaries_len              struct fields
    libnemo_relay.so            build artefacts

Exit status is 0 when every identifier is present, 1 when any is missing, and 2 on a usage or
network error. So this can gate a pipeline, though its real use is the table it prints.

Two cautions about what a pass means. Presence in the diff is necessary, not sufficient: a real
name used to describe behaviour it does not have will still pass. And absence is not always
fabrication — a name may be real but pre-existing rather than added by this pull request, which
is a misattribution rather than an invention. Use --repo-wide to tell those apart.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request

API = "https://api.github.com"


def http_get(url: str, token: str | None, accept: str = "application/vnd.github+json") -> bytes:
    req = urllib.request.Request(url, headers={
        "Accept": accept,
        "User-Agent": "verify-grounding",
        **({"Authorization": f"Bearer {token}"} if token else {}),
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf8", "replace")[:200]
        if e.code == 403 and "rate limit" in body.lower():
            die("GitHub rate limit. Set GITHUB_TOKEN for 5000 requests/hour instead of 60 shared.")
        die(f"HTTP {e.code} for {url}\n{body}")
    except urllib.error.URLError as e:
        die(f"cannot reach {url}: {e.reason}")


def die(msg: str, code: int = 2):
    print(f"error: {msg}", file=sys.stderr)
    raise SystemExit(code)


def load_identifiers(path: str) -> list[tuple[str, str]]:
    """Return (identifier, category) pairs, preserving file order within each category."""
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    with open(path) as fh:
        for raw in fh:
            line = raw.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            parts = re.split(r"\t|  +", line.strip(), maxsplit=1)
            name = parts[0].strip()
            cat = parts[1].strip() if len(parts) > 1 else "uncategorised"
            if name in seen:
                continue
            seen.add(name)
            out.append((name, cat))
    if not out:
        die(f"no identifiers found in {path}")
    return out


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--repo", required=True, metavar="OWNER/NAME")
    p.add_argument("--pr", required=True, type=int)
    p.add_argument("--identifiers", required=True, metavar="FILE")
    p.add_argument("--repo-wide", action="store_true",
                   help="for each miss, also search the repository's default branch, to tell "
                        "a fabricated name from one that is real but not added by this PR")
    p.add_argument("--json", metavar="FILE", help="write machine-readable results here")
    args = p.parse_args()

    if "/" not in args.repo:
        die("--repo must be OWNER/NAME")
    token = os.environ.get("GITHUB_TOKEN")

    meta = json.loads(http_get(f"{API}/repos/{args.repo}/pulls/{args.pr}", token))
    diff = http_get(f"{API}/repos/{args.repo}/pulls/{args.pr}",
                    token, accept="application/vnd.github.v3.diff").decode("utf8", "replace")

    idents = load_identifiers(args.identifiers)
    results = []
    for name, cat in idents:
        present = name in diff
        note = ""
        if not present and args.repo_wide:
            q = urllib.parse.quote(f'"{name}" repo:{args.repo}')
            try:
                hits = json.loads(http_get(f"{API}/search/code?q={q}&per_page=1", token))
                note = ("exists in repo, not added by this PR"
                        if hits.get("total_count", 0) > 0 else "not in repo either")
            except SystemExit:
                note = "repo-wide search unavailable (needs an authenticated token)"
        results.append({"identifier": name, "category": cat, "in_diff": present, "note": note})

    # ---- report -----------------------------------------------------------
    print(f"PR #{meta['number']}  {meta['title']}")
    print(f"by {meta['user']['login']} · {meta['changed_files']} files "
          f"+{meta['additions']}/-{meta['deletions']} · {meta['html_url']}")
    print()

    cats: dict[str, list[dict]] = {}
    for r in results:
        cats.setdefault(r["category"], []).append(r)

    width = max(len(c) for c in cats) + 2
    print(f"{'category'.ljust(width)}{'cited':>7}{'verbatim':>10}")
    print("-" * (width + 17))
    for cat, rows in cats.items():
        good = sum(1 for r in rows if r["in_diff"])
        print(f"{cat.ljust(width)}{len(rows):>7}{good:>10}"
              + ("" if good == len(rows) else "   <-- "
                 + ", ".join(r["identifier"] for r in rows if not r["in_diff"])))
    total, ok = len(results), sum(1 for r in results if r["in_diff"])
    print("-" * (width + 17))
    print(f"{'TOTAL'.ljust(width)}{total:>7}{ok:>10}   ({100 * ok / total:.1f}%)")

    missing = [r for r in results if not r["in_diff"]]
    if missing:
        print("\nnot present in the diff:")
        for r in missing:
            print(f"  {r['identifier']}" + (f"  — {r['note']}" if r["note"] else ""))
        print("\nA miss is worth reading before you act on it. A name that exists in the repository\n"
              "but not in this diff is a misattribution; a name that exists nowhere is invented.\n"
              "Both mislead a reader, and only the second one is the model making something up.")

    if args.json:
        with open(args.json, "w") as fh:
            json.dump({"repo": args.repo, "pr": args.pr, "title": meta["title"],
                       "author": meta["user"]["login"], "changed_files": meta["changed_files"],
                       "additions": meta["additions"], "deletions": meta["deletions"],
                       "cited": total, "verbatim": ok, "results": results}, fh, indent=2)
        print(f"\nwrote {args.json}")

    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
