# SPDX-License-Identifier: Apache-2.0

"""Validate optional Resource-menu links without making startup depend on the network."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import re
from urllib.request import Request, urlopen


LINK = re.compile(r'\s*<a data-bac-resource href="([^"]+)"[^>]*>.*?</a>', re.DOTALL)
MENU = re.compile(r'\s*<details id="studio-resources".*?</details>', re.DOTALL)


def available(url, timeout=4):
    request = Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (compatible; NVIDIA-BaC-LinkCheck/1.0)',
        'Accept': 'text/html,application/xhtml+xml,*/*;q=0.8',
    })
    try:
        with urlopen(request, timeout=timeout) as response:
            return 200 <= response.status < 300
    except Exception:
        return False


def filter_page(path, checker=available):
    """Remove unverified resource links from a generated page, returning kept URLs."""
    path = Path(path)
    page = path.read_text(encoding='utf-8')
    menu = MENU.search(page)
    if not menu:
        return []
    links = list(LINK.finditer(menu.group()))
    def verify(match):
        try:
            return checker(match.group(1)) is True
        except Exception:
            return False
    with ThreadPoolExecutor(max_workers=max(1, len(links))) as pool:
        results = list(pool.map(verify, links))
    kept = [match.group(1) for match, valid in zip(links, results) if valid]
    filtered = menu.group()
    for match, valid in reversed(list(zip(links, results))):
        if not valid:
            filtered = filtered[:match.start()] + filtered[match.end():]
    if not kept:
        filtered = ''
    path.write_text(page[:menu.start()] + filtered + page[menu.end():], encoding='utf-8')
    print(f'Resource links verified: {len(kept)}/{len(links)} available.', flush=True)
    return kept
