# SPDX-License-Identifier: Apache-2.0
"""Rebuild the offline city table from the three GeoNames dump files in a directory."""
import argparse
import csv
from decimal import Decimal, ROUND_DOWN
import gzip
import io
from pathlib import Path
import unicodedata
import zipfile


def coordinate(value):
    return format(Decimal(value).quantize(Decimal('.0001'), rounding=ROUND_DOWN).normalize(), 'f')


def normalized(value):
    return ''.join(c for c in unicodedata.normalize('NFKD', value.casefold()) if c.isalnum())


def build(source, output):
    with (source / 'countryInfo.txt').open(encoding='utf-8') as f:
        countries = {r[0]: r[4] for r in csv.reader((s for s in f if not s.startswith('#')), delimiter='\t')}
    with (source / 'admin1CodesASCII.txt').open(encoding='utf-8') as f:
        regions = {r[0]: r[1] for r in csv.reader(f, delimiter='\t')}
    with zipfile.ZipFile(source / 'cities15000.zip') as archive, archive.open('cities15000.txt') as raw, \
            output.open('wb') as dest, gzip.GzipFile(fileobj=dest, filename='', mode='wb', mtime=0) as compressed:
        for r in csv.reader(io.TextIOWrapper(raw, encoding='utf-8'), delimiter='\t', quoting=csv.QUOTE_NONE):
            name, ascii_name, alternates, lat, lon = r[1:6]
            country, region, population, zone = r[8], r[10], r[14], r[17]
            # Exact official names take precedence over alternate spellings at lookup time.
            keys = {normalized(n) for n in (name, ascii_name)} - {''}
            aliases = sorted({normalized(n) for n in alternates.split(',')} - keys - {''})
            fields = [name, ascii_name if ascii_name != name else '', country, region,
                      coordinate(lat), coordinate(lon), zone, population or '0',
                      countries.get(country, ''), regions.get(country + '.' + region, ''),
                      ' '.join(sorted(keys)), ' '.join(aliases)]
            compressed.write(('\t'.join(fields) + '\n').encode())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    args = parser.parse_args()
    build(args.source, Path(__file__).resolve().parents[1] / 'runtime/research-guard/weather/cities.tsv.gz')
