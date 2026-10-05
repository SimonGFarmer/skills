"""Read Archive II with Py-ART; export reader arrays and masks, plus JSON summary."""
import argparse
import contextlib
import json
import sys
from pathlib import Path

def field_summary(values):
    import numpy as np
    data = np.ma.masked_invalid(values)
    valid = data.compressed()
    return {'shape': list(data.shape), 'masked_gates': int(np.ma.getmaskarray(data).sum()), 'valid_gates': int(valid.size), 'min': float(valid.min()) if valid.size else None, 'max': float(valid.max()) if valid.size else None}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('file')
    parser.add_argument('--npz', help='Optional Py-ART array export; upstream mixed-resolution interpolation may apply')
    args = parser.parse_args()
    with contextlib.redirect_stdout(sys.stderr):
        import numpy as np
        import pyart
        radar = pyart.io.read_nexrad_archive(args.file)
    fields = {name: dict(field_summary(field['data']), units=field.get('units'), standard_name=field.get('standard_name')) for name, field in radar.fields.items()}
    result = {'source_file': str(Path(args.file).resolve()), 'reader': 'Py-ART ' + pyart.__version__, 'rays': radar.nrays, 'gates': radar.ngates, 'sweeps': radar.nsweeps, 'latitude': radar.latitude['data'].tolist(), 'longitude': radar.longitude['data'].tolist(), 'altitude_m': radar.altitude['data'].tolist(), 'time_units': radar.time['units'], 'ray_time_offset_seconds_min': float(radar.time['data'].min()), 'ray_time_offset_seconds_max': float(radar.time['data'].max()), 'fields': fields}
    if args.npz:
        path = Path(args.npz)
        if path.exists():
            raise ValueError('Refusing to overwrite NPZ')
        arrays = {name: getattr(radar, name)['data'] for name in ['range', 'azimuth', 'elevation', 'time', 'sweep_start_ray_index', 'sweep_end_ray_index', 'fixed_angle', 'latitude', 'longitude', 'altitude']}
        for name, field in radar.fields.items():
            values = np.ma.masked_invalid(field['data'])
            arrays[name] = values.filled(np.nan)
            arrays[name + '__mask'] = np.ma.getmaskarray(values)
        for name in ['gate_x', 'gate_y', 'gate_z', 'gate_latitude', 'gate_longitude', 'gate_altitude']:
            arrays[name] = getattr(radar, name)['data']
        with path.open('xb') as output:
            np.savez_compressed(output, **arrays)
        result['npz'] = str(path.resolve())
    print(json.dumps(result, indent=2, allow_nan=False))

if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(json.dumps({'error': str(error)}), file=sys.stderr)
        sys.exit(1)
