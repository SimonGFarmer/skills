"""Emit official NWS WSR-88D stations as JSON, optionally nearest first."""
import argparse
import json
import math
import sys
from archive import request

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lat', type=float)
    parser.add_argument('--lon', type=float)
    args = parser.parse_args()
    if (args.lat is None) != (args.lon is None):
        parser.error('Supply both --lat and --lon')
    if args.lat is not None and not (-90 <= args.lat <= 90 and -180 <= args.lon <= 180):
        parser.error('Invalid latitude/longitude')
    with request('https://api.weather.gov/radar/stations') as response:
        data = json.load(response)
    rows = []
    for feature in data['features']:
        props = feature['properties']
        if props.get('stationType') != 'WSR-88D':
            continue
        lon, lat = feature['geometry']['coordinates'][:2]
        row = {'station': props['id'], 'name': props.get('name'), 'longitude': lon, 'latitude': lat}
        if args.lat is not None:
            a, b = math.radians(args.lat), math.radians(lat)
            h = math.sin((b-a)/2)**2 + math.cos(a)*math.cos(b)*math.sin(math.radians(lon-args.lon)/2)**2
            row['distance_km'] = 6371 * 2 * math.asin(min(1, math.sqrt(h)))
        rows.append(row)
    print(json.dumps(sorted(rows, key=lambda row: row.get('distance_km', row['station'])), indent=2))

if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(json.dumps({'error': str(error)}), file=sys.stderr)
        sys.exit(1)
