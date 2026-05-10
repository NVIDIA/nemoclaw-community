#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""
Look up technical jargon definitions using Wikipedia or Free Dictionary API.
Designed to run inside a NemoClaw sandbox with whitelisted network access.

Usage:
    python3 lookup-jargon.py "eigenvalue"
    python3 lookup-jargon.py "eigenvalue" "Fourier transform" "matrix"
    python3 lookup-jargon.py "eigenvalue" --source wikipedia
    python3 lookup-jargon.py "eigenvalue" --source dictionary
    python3 lookup-jargon.py "eigenvalue" "Fourier transform" --json

Disambiguation (important for ambiguous terms):
    python3 lookup-jargon.py "transformer" --context "machine learning"
    python3 lookup-jargon.py "CNN" --context "neural network"
    python3 lookup-jargon.py "tensor" --context "deep learning"

Sources:
    auto        Try Wikipedia first, fall back to Free Dictionary (default)
    wikipedia   Only use Wikipedia REST API
    dictionary  Only use Free Dictionary API
"""
import sys, json, urllib.request, urllib.parse, urllib.error, argparse, textwrap

_UA = {
    "User-Agent": "NemoClaw-HermesOmni-Demo/1.0 (https://github.com/brevdev/nemoclaw-demos)",
    "Accept": "application/json",
}


def search_wikipedia_best_match(term: str, context: str):
    """Use Wikipedia search API to find the best article title for term+context.

    Returns the title of the top-ranked result, or None if search fails.
    This disambiguates ambiguous terms — e.g., 'transformer' + 'machine learning'
    returns 'Transformer (deep learning)' instead of the electrical device article.
    """
    query = f"{term} {context}".strip()
    encoded = urllib.parse.quote(query)
    url = (
        f"https://en.wikipedia.org/w/api.php"
        f"?action=query&list=search&srsearch={encoded}&srlimit=1&format=json"
    )
    req = urllib.request.Request(url, headers=_UA)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        results = data.get("query", {}).get("search", [])
        return results[0]["title"] if results else None
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, KeyError):
        return None


def lookup_wikipedia(term: str, context: str = None):
    """Look up a term on Wikipedia REST API. Returns dict or None on failure."""
    title = None
    if context:
        title = search_wikipedia_best_match(term, context)

    lookup_title = title or term.replace(" ", "_")
    encoded = urllib.parse.quote(lookup_title, safe="")
    url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{encoded}"

    req = urllib.request.Request(url, headers=_UA)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        if data.get("type") == "disambiguation":
            extract = data.get("extract", "Multiple meanings found.")
            return {
                "term": term,
                "source": "wikipedia",
                "definition": f"(Disambiguation) {extract}",
                "url": data.get("content_urls", {}).get("desktop", {}).get("page", ""),
                "context_used": context,
            }
        return {
            "term": term,
            "source": "wikipedia",
            "title": data.get("title", term),
            "definition": data.get("extract", "No summary available."),
            "description": data.get("description", ""),
            "url": data.get("content_urls", {}).get("desktop", {}).get("page", ""),
            "context_used": context,
        }
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    except (urllib.error.URLError, OSError) as e:
        msg = str(e)
        if "403" in msg or "Forbidden" in msg or "CONNECT" in msg:
            print("  [BLOCKED] Wikipedia access denied by NemoClaw network policy.", file=sys.stderr)
        else:
            print(f"  [ERROR] Wikipedia request failed: {e}", file=sys.stderr)
        return None


def lookup_dictionary(term: str):
    """Look up a term on Free Dictionary API. Returns dict or None on failure."""
    encoded = urllib.parse.quote(term.lower(), safe="")
    url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{encoded}"

    req = urllib.request.Request(url, headers={"User-Agent": _UA["User-Agent"]})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        if not data or not isinstance(data, list):
            return None
        entry = data[0]
        definitions = []
        for meaning in entry.get("meanings", []):
            pos = meaning.get("partOfSpeech", "")
            for defn in meaning.get("definitions", [])[:2]:
                text = defn.get("definition", "")
                if text:
                    definitions.append(f"({pos}) {text}" if pos else text)
        return {
            "term": term,
            "source": "dictionary",
            "definition": " | ".join(definitions[:4]) if definitions else "No definition found.",
            "phonetic": entry.get("phonetic", ""),
        }
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    except (urllib.error.URLError, OSError) as e:
        msg = str(e)
        if "403" in msg or "Forbidden" in msg or "CONNECT" in msg:
            print("  [BLOCKED] Free Dictionary access denied by NemoClaw network policy.", file=sys.stderr)
        else:
            print(f"  [ERROR] Dictionary request failed: {e}", file=sys.stderr)
        return None


def lookup_term(term: str, source: str = "auto", context: str = None) -> dict:
    """Look up a single term. Returns result dict with 'found' key."""
    if source == "wikipedia":
        result = lookup_wikipedia(term, context)
        if result:
            return {**result, "found": True}
        return {"term": term, "source": "wikipedia", "found": False,
                "error": f"'{term}' not found on Wikipedia."}

    if source == "dictionary":
        result = lookup_dictionary(term)
        if result:
            return {**result, "found": True}
        return {"term": term, "source": "dictionary", "found": False,
                "error": f"'{term}' not found in Free Dictionary."}

    result = lookup_wikipedia(term, context)
    if result:
        return {**result, "found": True}

    result = lookup_dictionary(term)
    if result:
        return {**result, "found": True}

    return {"term": term, "source": "none", "found": False,
            "error": f"'{term}' not found on Wikipedia or Free Dictionary."}


def print_result(r: dict):
    if not r["found"]:
        print(f"\n  {r['term']}: {r['error']}")
        return

    header = f"=== {r['term']}"
    if r.get("title") and r["title"].lower() != r["term"].lower():
        header += f" → {r['title']}"
    header += " ==="
    print(f"\n  {header}")
    print(f"  Source: {r['source'].title()}")
    if r.get("context_used"):
        print(f"  Context: {r['context_used']}")
    if r.get("description"):
        print(f"  ({r['description']})")
    definition = r.get("definition", "")
    wrapped = textwrap.fill(definition, width=76, initial_indent="  ", subsequent_indent="  ")
    print(wrapped)
    if r.get("url"):
        print(f"  Link: {r['url']}")


def main():
    parser = argparse.ArgumentParser(
        description="Look up jargon definitions via Wikipedia or Free Dictionary",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Network Policy:
              This script is designed to run inside a NemoClaw sandbox.
              Only whitelisted websites (Wikipedia, Free Dictionary) are accessible.
              Attempts to reach other sites will be blocked by the L7 proxy.
        """),
    )
    parser.add_argument("terms", nargs="+", help="Terms to look up")
    parser.add_argument("--source", "-s", choices=["auto", "wikipedia", "dictionary"],
                        default="auto", help="Which source to use (default: auto)")
    parser.add_argument("--context", "-c", default=None,
                        help="Domain context to disambiguate (e.g., 'machine learning', 'physics')")
    parser.add_argument("--json", "-j", dest="json_output", action="store_true",
                        help="Output results as JSON")

    args = parser.parse_args()
    results = []

    for term in args.terms:
        result = lookup_term(term.strip(), args.source, args.context)
        results.append(result)

    if args.json_output:
        print(json.dumps(results, indent=2))
    else:
        found = sum(1 for r in results if r["found"])
        ctx_label = f", context: {args.context}" if args.context else ""
        print(f"Looking up {len(args.terms)} term(s) [source: {args.source}{ctx_label}]...")
        for r in results:
            print_result(r)
        print(f"\n[{found}/{len(results)} terms found]")


if __name__ == "__main__":
    main()
