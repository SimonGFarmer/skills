"""Anonymous, bounded NOAA/Unidata Archive II discovery and downloads (stdlib)."""
import argparse
import datetime as dt
import json
import pathlib
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

BASE = 'https://unidata-nexrad-level2.s3.amazonaws.com/'
NS = {'s': 'http://s3.amazonaws.com/doc/2006-03-01/'}

def utc(value):
    result = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('Time must include Z or a UTC offset')
    return result.astimezone(dt.timezone.utc)

def request(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'nexrad-skill/1.0 (NOAA data analysis)'}), timeout=60)

def discover(station, start, end, fetch=request):
    if not re.fullmatch(r'[A-Z][A-Z0-9]{3}', station):
        raise ValueError('Station must be a four-character radar ID')
    if not start < end or end - start > dt.timedelta(days=7):
        raise ValueError('Require start < end and a window of at most 7 days; split larger requests')
    found = {}
    day = start.date()
    while day <= end.date():
        prefix = f'{day:%Y/%m/%d}/{station}/'
        token = None
        seen = set()
        while True:
            query = {'list-type': '2', 'prefix': prefix, 'max-keys': '1000'}
            if token:
                query['continuation-token'] = token
            with fetch(BASE + '?' + urllib.parse.urlencode(query)) as response:
                root = ET.fromstring(response.read())
            for item in root.findall('s:Contents', NS):
                key = item.findtext('s:Key', namespaces=NS)
                match = re.fullmatch(station + r'(\d{8})_(\d{6})(?:_V\d+)?(?:\.gz)?', pathlib.PurePosixPath(key).name)
                if not match:
                    continue
                stamp = dt.datetime.strptime(''.join(match.groups()), '%Y%m%d%H%M%S').replace(tzinfo=dt.timezone.utc)
                if start <= stamp < end:
                    found[key] = {'key': key, 'key_time_utc': stamp.isoformat(), 'size_bytes': int(item.findtext('s:Size', namespaces=NS)), 'last_modified': item.findtext('s:LastModified', namespaces=NS), 'url': BASE + urllib.parse.quote(key)}
            if root.findtext('s:IsTruncated', namespaces=NS) != 'true':
                break
            token = root.findtext('s:NextContinuationToken', namespaces=NS)
            if not token or token in seen:
                raise ValueError('Invalid or repeated S3 continuation token')
            seen.add(token)
        day += dt.timedelta(days=1)
    return sorted(found.values(), key=lambda row: row['key'])

def download(rows, directory, max_files, max_bytes, fetch=request):
    if max_files < 1 or max_bytes < 1:
        raise ValueError('Download caps must be positive')
    selected = rows[:max_files]
    if sum(row['size_bytes'] for row in selected) > max_bytes:
        raise ValueError('Selected files exceed byte cap; narrow the window or file cap')
    directory = pathlib.Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    total = 0
    for row in selected:
        target = directory / pathlib.PurePosixPath(row['key']).name
        if target.exists():
            raise ValueError(f'Refusing to overwrite {target}')
        temporary = target.with_suffix(target.suffix + '.part')
        if temporary.exists():
            raise ValueError(f'Refusing to overwrite partial file {temporary}')
        created = False
        try:
            with temporary.open('xb') as output:
                created = True
                count = 0
                with fetch(row['url']) as response:
                    while chunk := response.read(1024 * 1024):
                        count += len(chunk)
                        total += len(chunk)
                        if count > row['size_bytes'] or total > max_bytes:
                            raise ValueError('Response exceeded expected size or byte cap')
                        output.write(chunk)
            if count != row['size_bytes']:
                raise ValueError('Incomplete download')
            temporary.rename(target)
            row['local_path'] = str(target.resolve())
        except BaseException:
            if created:
                temporary.unlink(missing_ok=True)
            raise
    return selected

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--station', required=True)
    parser.add_argument('--start', required=True)
    parser.add_argument('--end', required=True)
    parser.add_argument('--download', metavar='DIRECTORY')
    parser.add_argument('--max-files', type=int, default=1)
    parser.add_argument('--max-bytes', type=int, default=50000000)
    args = parser.parse_args()
    rows = discover(args.station.upper(), utc(args.start), utc(args.end))
    if args.download:
        rows = download(rows, args.download, args.max_files, args.max_bytes)
    print(json.dumps({'station': args.station.upper(), 'selection_basis': 'key time, start inclusive/end exclusive; not volume completion', 'observations': rows}, indent=2))

if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(json.dumps({'error': str(error)}), file=sys.stderr)
        sys.exit(1)
