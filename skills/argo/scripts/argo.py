#!/usr/bin/env python3
"""Bounded core Argo GDAC discovery, retrieval and QC-aware decoding."""
import argparse
import csv
import datetime as dt
import gzip
import hashlib
import http.client
import io
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
import urllib.request
import zlib

BASE = 'https://data-argo.ifremer.fr/'
INDEX = 'ar_index_global_prof.txt.gz'
INDEX_URLS = {'ifremer': BASE+INDEX,
              'aws': 'https://argo-gdac-sandbox.s3.eu-west-3.amazonaws.com/pub/idx/'+INDEX}
PATTERN = re.compile(r'(?P<dac>[a-z0-9_]+)/(?P<wmo>[0-9]{5,8})/profiles/(?P<file>[RD](?P=wmo)_[0-9]{3,4}D?\.nc)\Z')

def utc():
    return dt.datetime.now(dt.timezone.utc).isoformat()

def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024*1024), b''):
            h.update(chunk)
    return h.hexdigest()

def provenance(path, expected_url=None):
    sidecar = Path(str(path)+'.json')
    m = json.loads(sidecar.read_text())
    if not isinstance(m, dict) or not all(k in m for k in ('url','sha256','bytes','retrieved_utc')):
        raise ValueError('Missing provenance fields')
    if not isinstance(m['url'], str) or not (m['url'].startswith(BASE) or m['url'] == INDEX_URLS['aws']) or not m['retrieved_utc']:
        raise ValueError('Invalid provenance URL/time')
    if not isinstance(m['retrieved_utc'], str):
        raise ValueError('Invalid provenance timestamp')
    stamp = dt.datetime.fromisoformat(m['retrieved_utc'])
    if stamp.utcoffset() != dt.timedelta(0):
        raise ValueError('Provenance timestamp must be UTC')
    if expected_url is not None and m['url'] != expected_url:
        raise ValueError('Cached URL does not match requested source')
    if m['bytes'] != Path(path).stat().st_size or m['sha256'] != digest(path):
        raise ValueError('Cached bytes do not match provenance')
    return m

def download(url, output, max_bytes):
    """Exclusive output; failed sidecar writes remove newly created data."""
    if max_bytes < 1:
        raise ValueError('Byte cap must be positive')
    output = Path(output)
    sidecar = Path(str(output)+'.json')
    if output.exists() or sidecar.exists():
        if output.exists() and sidecar.exists():
            return provenance(output, url)
        raise ValueError('Incomplete cache entry; choose another output or inspect/remove it')
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=output.parent, prefix='.argo-')
    created = False
    try:
        with os.fdopen(fd, 'wb') as f, urllib.request.urlopen(
                urllib.request.Request(url, headers={'User-Agent':'argo-skill/1.0'}), timeout=60) as r:
            if r.geturl().split('/')[2] != url.split('/')[2]:
                raise ValueError('Unexpected download redirect host')
            length = r.headers.get('Content-Length')
            if length and int(length) > max_bytes:
                raise ValueError('Download exceeds byte cap')
            total = 0
            while True:
                b = r.read(min(1024*1024, max_bytes-total+1))
                if not b: break
                total += len(b)
                if total > max_bytes: raise ValueError('Download exceeds byte cap')
                f.write(b)
            if not total: raise ValueError('Empty download')
            if length and total != int(length): raise ValueError('Incomplete download')
        m = {'url':url, 'bytes':total, 'sha256':digest(tmp), 'retrieved_utc':utc()}
        # Copy with exclusive creation: never replace an existing destination.
        with open(output, 'xb') as dest, open(tmp, 'rb') as src:
            created = True
            for b in iter(lambda: src.read(1024*1024), b''): dest.write(b)
        try:
            with open(sidecar, 'x') as f: json.dump(m, f, indent=2)
        except Exception:
            if sidecar.exists():
                # Do not delete a pre-existing sidecar from another writer.
                pass
            raise
        return m
    except Exception:
        if created: output.unlink(missing_ok=True)
        raise
    finally:
        Path(tmp).unlink(missing_ok=True)

def time_arg(s):
    try: return dt.datetime.strptime(s,'%Y-%m-%d').strftime('%Y%m%d000000')
    except ValueError as e: raise argparse.ArgumentTypeError('Use YYYY-MM-DD UTC') from e

def discover(path, start, end, bbox, wmo, limit):
    if start >= end: raise ValueError('Start must precede exclusive end')
    if not 1 <= limit <= 1000: raise ValueError('Limit must be 1..1000')
    if bbox:
        west,south,east,north = bbox
        if not all(math.isfinite(x) for x in bbox) or not(-180<=west<=180 and -180<=east<=180 and -90<=south<=north<=90):
            raise ValueError('Invalid bbox; use west south east north in degrees')
    if wmo and not re.fullmatch(r'[0-9]{5,8}',wmo): raise ValueError('Invalid WMO identifier')
    meta=provenance(path)
    if meta['url'] not in INDEX_URLS.values(): raise ValueError('Not a supported core index source')
    rows=[]; matches=0
    opener=gzip.open if str(path).endswith('.gz') else open
    with opener(path,'rt',encoding='utf-8',newline='') as f:
        reader=csv.DictReader((line for line in f if not line.startswith('#')), strict=True)
        required={'file','date','latitude','longitude','date_update'}
        if not required.issubset(reader.fieldnames or []): raise ValueError('Invalid core index header')
        for line,row in enumerate(reader,2):
            if None in row or any(row.get(k) is None for k in required):
                raise ValueError(f'Malformed index row {line}')
            match=PATTERN.fullmatch(row['file'])
            if not match: raise ValueError(f'Unexpected core profile path at row {line}')
            if wmo and match['wmo'] != wmo: continue
            date=row['date']
            if not date: continue
            if not re.fullmatch(r'[0-9]{14}',date): raise ValueError(f'Invalid date at row {line}')
            dt.datetime.strptime(date, '%Y%m%d%H%M%S')
            if row['date_update']:
                dt.datetime.strptime(row['date_update'], '%Y%m%d%H%M%S')
            if not start<=date<end: continue
            if row['latitude'] and row['longitude']:
                lat,lon=float(row['latitude']),float(row['longitude'])
                if not (math.isfinite(lat) and math.isfinite(lon) and -90<=lat<=90 and -180<=lon<=180):
                    raise ValueError(f'Invalid coordinates at row {line}')
            if bbox:
                try: lat,lon=float(row['latitude']),float(row['longitude'])
                except ValueError: continue
                if not (math.isfinite(lat) and math.isfinite(lon) and south<=lat<=north): continue
                if not ((west<=lon<=east) if west<=east else (lon>=west or lon<=east)): continue
            matches+=1
            if len(rows)<limit: rows.append(dict(row,wmo=match['wmo'],url=BASE+'dac/'+row['file']))
    return {'index':meta,'start_inclusive':start,'end_exclusive':end,'bbox':bbox,'wmo':wmo,
            'matches':matches,'returned':len(rows),'truncated':matches>limit,'order':'source index order','profiles':rows}

def chars(value):
    import numpy as np
    a=np.ma.asarray(value)
    if np.ma.getmaskarray(a).all(): return ''
    return b''.join(a.filled(b' ').astype('S1').ravel()).decode('ascii').strip()

def number(value):
    import numpy as np
    if np.ma.is_masked(value): return None
    v=float(value)
    return v if math.isfinite(v) else None

def decode(path, qc, max_levels):
    import netCDF4
    if not qc or any(x not in ('1','2') for x in qc): raise ValueError('QC policy accepts only 1 or 1,2')
    if max_levels < 1 or max_levels>1000000: raise ValueError('Invalid max-levels cap')
    source=provenance(path)
    if not source['url'].startswith(BASE+'dac/') or not PATTERN.fullmatch(source['url'][len(BASE+'dac/'):]):
        raise ValueError('Expected core per-cycle GDAC provenance')
    result=[]
    with netCDF4.Dataset(path) as ds:
        ds.set_auto_chartostring(False)
        if 'N_PROF' not in ds.dimensions or 'N_LEVELS' not in ds.dimensions: raise ValueError('Not an Argo profile file')
        if len(ds.dimensions['N_PROF'])*len(ds.dimensions['N_LEVELS'])>max_levels: raise ValueError('Decoded level count exceeds cap')
        for i in range(len(ds.dimensions['N_PROF'])):
            mode=chars(ds['DATA_MODE'][i])
            if mode not in ('R','A','D'): raise ValueError('Unknown DATA_MODE')
            p={'profile_index':i,'wmo':chars(ds['PLATFORM_NUMBER'][i]),'cycle':number(ds['CYCLE_NUMBER'][i]),
               'direction':chars(ds['DIRECTION'][i]),'data_mode':mode,'latitude':number(ds['LATITUDE'][i]),
               'longitude':number(ds['LONGITUDE'][i]),'position_qc':chars(ds['POSITION_QC'][i]),
               'juld':number(ds['JULD'][i]),'juld_units':getattr(ds['JULD'],'units',None),
               'juld_qc':chars(ds['JULD_QC'][i]),'parameters':{}}
            for param in ('PRES','TEMP','PSAL'):
                name=param if mode=='R' else param+'_ADJUSTED'
                if name not in ds.variables or name+'_QC' not in ds.variables: raise ValueError('Missing selected variable or QC: '+name)
                v=ds[name]; values=v[i]; flags=[chars(q) for q in ds[name+'_QC'][i]]
                vals=[number(x) for x in values]
                accepted=[v is not None and q in qc for v,q in zip(vals,flags)]
                error_name=param+'_ADJUSTED_ERROR' if mode!='R' else None
                errors=[number(x) for x in ds[error_name][i]] if error_name in ds.variables else [None]*len(vals)
                p['parameters'][param]={'source_variable':name,'units':getattr(v,'units',None),
                    'values':[v if ok else None for v,ok in zip(vals,accepted)],'qc':flags,'accepted':accepted,
                    'adjusted_error':errors,'error_variable':error_name if error_name in ds.variables else None}
            result.append(p)
    return {'source':source,'accepted_qc':qc,'profiles':result}

def main():
    p=argparse.ArgumentParser(description=__doc__); sub=p.add_subparsers(dest='command',required=True)
    d=sub.add_parser('index'); d.add_argument('--source',choices=INDEX_URLS,default='ifremer'); d.add_argument('--output',required=True); d.add_argument('--max-bytes',type=int,default=120_000_000)
    d=sub.add_parser('discover'); d.add_argument('--index',required=True); d.add_argument('--start',type=time_arg,required=True); d.add_argument('--end',type=time_arg,required=True); d.add_argument('--bbox',nargs=4,type=float); d.add_argument('--wmo'); d.add_argument('--limit',type=int,default=20)
    d=sub.add_parser('download'); d.add_argument('--profile',required=True); d.add_argument('--output',required=True); d.add_argument('--max-bytes',type=int,default=20_000_000)
    d=sub.add_parser('decode'); d.add_argument('--file',required=True); d.add_argument('--qc',default='1'); d.add_argument('--max-levels',type=int,default=100_000)
    a=p.parse_args()
    try:
        if a.command=='index': result=download(INDEX_URLS[a.source],a.output,a.max_bytes)
        elif a.command=='discover':
            if not a.bbox and not a.wmo: raise ValueError('Provide --bbox or --wmo')
            result=discover(a.index,a.start,a.end,a.bbox,a.wmo,a.limit)
        elif a.command=='download':
            if not PATTERN.fullmatch(a.profile): raise ValueError('Use exact core index file path DAC/WMO/profiles/[RD]WMO_CYCLE.nc')
            result=download(BASE+'dac/'+a.profile,a.output,a.max_bytes)
        else: result=decode(a.file,a.qc.split(','),a.max_levels)
        print(json.dumps(result,indent=2,allow_nan=False))
    except (ValueError,OSError,KeyError,EOFError,ImportError,csv.Error,RuntimeError,http.client.HTTPException,zlib.error) as e:
        print(json.dumps({'error':str(e)}),file=sys.stderr); return 2
    return 0
if __name__=='__main__': sys.exit(main())
