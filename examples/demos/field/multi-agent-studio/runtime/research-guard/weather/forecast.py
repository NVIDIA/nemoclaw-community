# SPDX-License-Identifier: Apache-2.0
"""Resolve cities locally and retrieve a compact MET Norway forecast."""
import argparse
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from email.parser import Parser
from email.utils import parsedate_to_datetime
import fcntl
import gzip
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unicodedata
from zoneinfo import ZoneInfo

DATA = Path(__file__).with_name('cities.tsv.gz')
ENDPOINT = 'https://api.met.no/weatherapi/locationforecast/2.0/compact'
USER_AGENT = 'NVIDIA-Multi-Agent-Studio (+https://www.nvidia.com/en-us/contact/)'
LICENSE = 'https://creativecommons.org/licenses/by/4.0/'


def normalize(name):
    text = unicodedata.normalize('NFKD', name.casefold())
    return ''.join(c for c in text if c.isalnum())


def cities(city, country='', region=''):
    city_name, *suffixes = (part.strip() for part in city.split(','))
    key = normalize(city_name)
    if not key:
        return []
    qualifiers = {normalize(part) for part in suffixes if part}
    country, region = normalize(country), normalize(region)
    words = city_name.split()
    # Also accept a trailing region without a comma, e.g. "Paris Texas".
    shorthand = {normalize(' '.join(words[:i])): normalize(' '.join(words[i:]))
                 for i in range(1, len(words))}
    candidates = defaultdict(list)
    with gzip.open(DATA, 'rt', encoding='utf-8') as src:
        for line in src:
            name, ascii_name, cc, area, lat, lon, tz, *extra = line.rstrip('\n').split('\t')
            if extra:
                population, country_name, area_name, primary, aliases = extra
                keys = primary.split()
            else:
                # A protected workspace may still contain the previous city table.
                population, country_name, area_name, aliases = '0', '', '', ''
                keys = [normalize(name), normalize(ascii_name)]
            if key in keys:
                rank = 0
            elif any(k in shorthand for k in keys):
                rank = 1
            elif key in aliases.split():
                rank = 2
            else:
                continue
            countries = {cc.lower(), normalize(country_name)}
            regions = {normalize(area), normalize(area_name)}
            if country and country not in countries or region and region not in regions:
                continue
            if not qualifiers <= countries | regions:
                continue
            if rank == 1 and not any(shorthand.get(k) in countries | regions for k in keys):
                if key not in aliases.split():
                    continue
                rank = 2
            candidates[rank].append(dict(city=name, country=cc, region=area, lat=lat, lon=lon,
                                         timezone=tz, countryName=country_name, regionName=area_name, population=int(population)))
    if not candidates:
        return []
    return sorted(candidates[min(candidates)], key=lambda loc: loc['population'], reverse=True)


def lookup(city, country='', region='', days=3):
    matches = cities(city, country, region)
    # Population is an offline proxy for prominence. Close namesakes still need clarification.
    if len(matches) > 1:
        largest, next_largest = matches[0]['population'], matches[1]['population']
        if largest >= 100_000 and next_largest > 0 and largest >= 10 * next_largest:
            matches = matches[:1]
    for loc in matches:
        loc.pop('population')
    if len(matches) != 1:
        return {'status': 'ambiguous' if matches else 'unknown city',
                'locations': matches[:10], 'message': 'Clarify the city, country or region before fetching.',
                'citySource': 'GeoNames · https://www.geonames.org/'}
    loc = matches[0]
    url = f"{ENDPOINT}?lat={loc['lat']}&lon={loc['lon']}"
    forecast = retrieve(url)
    return summarize(forecast, loc, url, days)


def retrieve(url):
    # Use a private directory per runtime user. Protected runs have their own /tmp.
    directory = Path(tempfile.gettempdir()) / f'bac-met-forecast-{os.getuid()}'
    directory.mkdir(mode=0o700, exist_ok=True)
    if directory.is_symlink() or directory.stat().st_uid != os.getuid() or directory.stat().st_mode & 0o077:
        raise ValueError('Weather cache must be private.')
    cache = directory / sha256(url.encode()).hexdigest()
    with cache.with_suffix('.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            previous = json.loads(cache.read_text())
        except (FileNotFoundError, ValueError):
            previous = {}
        now = time.time()
        if previous.get('expires', 0) > now:
            return previous['data']
        with tempfile.TemporaryDirectory(dir=directory) as working:
            headers, body = Path(working)/'headers', Path(working)/'body'
            # OpenShell's network policy explicitly permits this binary, not Python HTTP.
            cmd = ['/usr/bin/curl', '--disable', '--silent', '--show-error', '--compressed', '--location', '--max-redirs', '3', '--proto-redir', '=https', '--max-time', '15',
                   '--max-filesize', '1500000', '--user-agent', USER_AGENT, '--dump-header', str(headers),
                   '--output', str(body), '--write-out', '%{http_code}']
            if previous.get('modified'):
                cmd += ['--header', 'If-Modified-Since: ' + previous['modified']]
            response = subprocess.run(cmd + [url], capture_output=True, text=True, timeout=18)
            if response.returncode:
                raise ValueError('Could not reach api.met.no. Check the connection or OpenShell Policy.')
            final_headers = headers.read_text().strip().split('\n\n')[-1].split('\n', 1)
            fields = Parser().parsestr(final_headers[1] if len(final_headers) > 1 else '')
            if response.stdout == '304' and 'data' in previous:
                data = previous['data']
            elif response.stdout in ('200', '203'):
                data = json.loads(body.read_bytes())
                if not data.get('properties', {}).get('timeseries'):
                    raise ValueError('No forecast periods returned by api.met.no.')
            else:
                raise ValueError(f'api.met.no returned HTTP {response.stdout}. No forecast available.')
            # Outside the Nordic countries MET recommends at least three hours between requests.
            expires = max(now + 10800, parsedate_to_datetime(fields['Expires']).timestamp() if fields['Expires'] else 0)
            saved = {'expires': expires, 'modified': fields.get('Last-Modified', previous.get('modified')), 'data': data}
            tmp = Path(working)/'cache'
            tmp.write_text(json.dumps(saved, separators=(',', ':')))
            tmp.replace(cache)
            return data


def summarize(forecast, location, url, days, now=None):
    now = now or datetime.now(timezone.utc)
    zone = ZoneInfo(location['timezone'])
    today = now.astimezone(zone).date()
    series = forecast['properties']['timeseries']
    daily = defaultdict(list)
    midday = {}
    upcoming = []
    for item in series:
        stamp = datetime.fromisoformat(item['time'].replace('Z', '+00:00')).astimezone(zone)
        if not today <= stamp.date() < today + timedelta(days=days):
            continue
        data = item['data']
        temp = data['instant']['details'].get('air_temperature')
        if temp is None:
            continue
        day = stamp.date().isoformat()
        daily[day].append(temp)
        sample = {'time': stamp.isoformat(timespec='minutes'), 'temperatureC': temp}
        for hours in (1, 6):
            period = data.get(f'next_{hours}_hours')
            if not period:
                continue
            sample['condition'] = period.get('summary', {}).get('symbol_code')
            sample['precipitationPeriodHours'] = hours
            if 'precipitation_amount' in period.get('details', {}):
                sample['precipitationMm'] = period['details']['precipitation_amount']
            break
        if stamp >= now - timedelta(hours=1) and len(upcoming) < 12:
            upcoming.append(sample)
        distance = abs(12 - stamp.hour)
        if sample.get('condition') and (day not in midday or distance < midday[day][0]):
            midday[day] = (distance, sample)
    return {'type': 'forecast', 'location': location, 'updatedAt': forecast['properties']['meta']['updated_at'],
            'upcoming': upcoming, 'dailyTemperatureSamples': [
                {'date': date, 'minC': min(values), 'maxC': max(values), 'samples': len(values)}
                for date, values in sorted(daily.items())],
            'representativePeriods': [midday[day][1] for day in sorted(midday)],
            'source': url, 'attribution': f'Forecast summarized from MET Norway ({LICENSE}); city coordinates from GeoNames (https://www.geonames.org/).',
            'coverage': 'Local dates; temperature ranges use available samples only. No forecast for omitted dates.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('city')
    parser.add_argument('--country', default='')
    parser.add_argument('--region', default='')
    parser.add_argument('--days', type=int, choices=range(1, 11), default=4)
    args = parser.parse_args()
    try:
        print(json.dumps(lookup(**vars(args)), ensure_ascii=False))
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
        parser.exit(1, f'Weather unavailable: {exc}\n')
