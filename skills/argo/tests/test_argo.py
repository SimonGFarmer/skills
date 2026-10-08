import contextlib
import gzip
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('argo',Path(__file__).parents[1]/'scripts'/'argo.py')
a=importlib.util.module_from_spec(spec); spec.loader.exec_module(a)

class ArgoTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name)
    def tearDown(self): self.tmp.cleanup()
    def meta(self,path,url):
        m={'url':url,'bytes':path.stat().st_size,'sha256':a.digest(path),'retrieved_utc':a.utc()}
        Path(str(path)+'.json').write_text(json.dumps(m)); return m
    def index(self,body):
        p=self.root/'index.gz'
        with gzip.open(p,'wt') as f: f.write('# comment\nfile,date,latitude,longitude,date_update\n'+body)
        self.meta(p,a.BASE+a.INDEX); return p
    def test_antimeridian_end_exclusion_and_truncation(self):
        p=self.index('aoml/1900050/profiles/D1900050_001.nc,20010101000000,0,179,20010102000000\naoml/1900050/profiles/D1900050_002.nc,20010101000000,0,-179,20010102000000\naoml/1900050/profiles/D1900050_003.nc,20020101000000,0,175,20020102000000\n')
        r=a.discover(p,'20010101000000','20020101000000',[170,-10,-170,10],None,1)
        self.assertEqual(r['matches'],2); self.assertTrue(r['truncated'])
    def test_truncated_csv(self):
        p=self.index('aoml/1900050/profiles/D1900050_001.nc,20010101000000\n')
        with self.assertRaisesRegex(ValueError,'Malformed'): a.discover(p,'2000','2002',None,'1900050',2)
    def test_missing_coordinates_wmo(self):
        p=self.index('aoml/1900050/profiles/D1900050_001.nc,20010101000000,,,20010102000000\n')
        self.assertEqual(a.discover(p,'2000','2002',None,'1900050',2)['matches'],1)
        self.assertEqual(a.discover(p,'2000','2002',[-180,-90,180,90],None,2)['matches'],0)
    def test_empty_sidecar_rejected(self):
        p=self.root/'file'; p.write_bytes(b'abc'); Path(str(p)+'.json').write_text('{}')
        with self.assertRaises(ValueError): a.provenance(p)
    def test_corrupted_cache(self):
        p=self.root/'file'; p.write_bytes(b'abc'); self.meta(p,a.BASE+a.INDEX); p.write_bytes(b'abd')
        with self.assertRaises(ValueError): a.provenance(p)
    def test_path_traversal_rejected(self):
        self.assertIsNone(a.PATTERN.fullmatch('../aoml/1900050/profiles/D1900050_001.nc'))
    def test_download_cap_and_cleanup(self):
        class Response(io.BytesIO):
            headers={}
            def geturl(self): return a.BASE+a.INDEX
        p=self.root/'file'
        with patch.object(a.urllib.request,'urlopen',return_value=Response(b'123456')):
            with self.assertRaises(ValueError): a.download(a.BASE+a.INDEX,p,3)
        self.assertFalse(p.exists()); self.assertFalse(list(self.root.glob('.argo-*')))
    def test_sidecar_failure_removes_new_data(self):
        class Response(io.BytesIO):
            headers={}
            def geturl(self): return a.BASE+a.INDEX
        p=self.root/'file'
        with patch.object(a.urllib.request,'urlopen',return_value=Response(b'123')), patch.object(a.json,'dump',side_effect=OSError('disk full')):
            with self.assertRaises(OSError): a.download(a.BASE+a.INDEX,p,9)
        self.assertFalse(p.exists())
    def fixture(self,mode):
        import netCDF4
        import numpy as np
        p=self.root/(mode+'.nc')
        with netCDF4.Dataset(p,'w') as ds:
            for k,n in [('N_PROF',1),('N_LEVELS',3),('STRING8',8)]: ds.createDimension(k,n)
            def char(name,dims,values): ds.createVariable(name,'S1',dims,fill_value=b' ')[:]=np.array(values,dtype='S1')
            char('DATA_MODE',('N_PROF',),[mode]); char('PLATFORM_NUMBER',('N_PROF','STRING8'),[list('1900050 ')])
            for name in ['DIRECTION','POSITION_QC','JULD_QC']: char(name,('N_PROF',),['1' if name!='DIRECTION' else 'A'])
            for name in ['CYCLE_NUMBER','LATITUDE','LONGITUDE','JULD']: ds.createVariable(name,'f8',('N_PROF',))[:]=[1]
            ds['JULD'].units='days since 1950-01-01 00:00:00 UTC'
            for param in ['PRES','TEMP','PSAL']:
                for suffix,vals in [('',[1,2,3]),('_ADJUSTED',[11,99999,13])]:
                    v=ds.createVariable(param+suffix,'f4',('N_PROF','N_LEVELS'),fill_value=99999); v[:]=[vals]; v.units='test_units'
                    char(param+suffix+'_QC',('N_PROF','N_LEVELS'),[['1','1','2']])
                ds.createVariable(param+'_ADJUSTED_ERROR','f4',('N_PROF','N_LEVELS'))[:]=[[.1,.2,.3]]
        self.meta(p,a.BASE+'dac/aoml/1900050/profiles/D1900050_001.nc'); return p
    def test_raw_mode_and_qc(self):
        r=a.decode(self.fixture('R'),['1'],100)['profiles'][0]['parameters']['TEMP']
        self.assertEqual(r['values'],[1,2,None]); self.assertIsNone(r['error_variable'])
    def test_adjusted_missing_never_raw_fallback(self):
        for mode in ['A','D']:
            r=a.decode(self.fixture(mode),['1','2'],100)['profiles'][0]['parameters']['TEMP']
            self.assertEqual(r['values'],[11,None,13]); self.assertEqual(r['source_variable'],'TEMP_ADJUSTED')
    def test_unknown_mode(self):
        with self.assertRaises(ValueError): a.decode(self.fixture('X'),['1'],100)
    def test_decode_cap(self):
        with self.assertRaises(ValueError): a.decode(self.fixture('D'),['1'],2)
    def test_bad_bounds(self):
        p=self.index('')
        with self.assertRaises(ValueError): a.discover(p,'2000','2002',[0,-91,10,10],None,2)
    def test_invalid_calendar_date(self):
        p=self.index('aoml/1900050/profiles/D1900050_001.nc,20011399000000,0,179,20010102000000\n')
        with self.assertRaises(ValueError): a.discover(p,'2000','2002',[170,-10,-170,10],None,2)
    def test_invalid_coordinate_range(self):
        p=self.index('aoml/1900050/profiles/D1900050_001.nc,20010101000000,0,999,20010102000000\n')
        with self.assertRaises(ValueError): a.discover(p,'2000','2002',[170,-10,-170,10],None,2)
    def test_bad_provenance_timestamp(self):
        p=self.root/'file'; p.write_bytes(b'abc'); m=self.meta(p,a.BASE+a.INDEX)
        m['retrieved_utc']={'not':'time'}; Path(str(p)+'.json').write_text(json.dumps(m))
        with self.assertRaises(ValueError): a.provenance(p)
    def test_short_content_length(self):
        class Response(io.BytesIO):
            headers={'Content-Length':'4'}
            def geturl(self): return a.BASE+a.INDEX
        p=self.root/'file'
        with patch.object(a.urllib.request,'urlopen',return_value=Response(b'123')):
            with self.assertRaises(ValueError): a.download(a.BASE+a.INDEX,p,9)
        self.assertFalse(p.exists())
    def test_nonpositive_byte_cap(self):
        with self.assertRaises(ValueError): a.download(a.BASE+a.INDEX,self.root/'file',0)
    def test_official_mirror_index_provenance(self):
        p=self.index('aoml/1900050/profiles/D1900050_001.nc,20010101000000,0,179,20010102000000\n')
        self.meta(p,a.INDEX_URLS['aws'])
        r=a.discover(p,'2000','2002',None,'1900050',2)
        self.assertEqual(r['index']['url'],a.INDEX_URLS['aws'])
        self.assertTrue(r['profiles'][0]['url'].startswith(a.BASE+'dac/'))
    def test_wrong_index_source(self):
        p=self.index(''); self.meta(p,a.BASE+'ar_index_global_meta.txt.gz')
        with self.assertRaises(ValueError): a.discover(p,'2000','2002',None,'1900050',2)
    def test_masked_char_scalar(self):
        import numpy as np
        self.assertEqual(a.chars(np.ma.masked),'')
    def test_fill_valued_qc(self):
        import netCDF4
        p=self.fixture('D')
        with netCDF4.Dataset(p,'a') as ds:
            ds['TEMP_ADJUSTED_QC'][0,0]=b' '
        self.meta(p,a.BASE+'dac/aoml/1900050/profiles/D1900050_001.nc')
        r=a.decode(p,['1'],100)['profiles'][0]['parameters']['TEMP']
        self.assertIsNone(r['values'][0]); self.assertEqual(r['qc'][0],'')
    def test_missing_adjusted_variable(self):
        import netCDF4
        p=self.fixture('D')
        with netCDF4.Dataset(p,'a') as ds: ds.renameVariable('TEMP_ADJUSTED','REMOVED')
        self.meta(p,a.BASE+'dac/aoml/1900050/profiles/D1900050_001.nc')
        with self.assertRaises(ValueError): a.decode(p,['1'],100)
if __name__=='__main__': unittest.main()
