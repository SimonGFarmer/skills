import io
import pathlib
import sys
import tempfile
import unittest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'skills/nexrad/scripts'))
import archive
from decode import field_summary

def page(keys, token=None):
    items = ''.join(f'<Contents><Key>{k}</Key><Size>3</Size><LastModified>2024-05-06T00:00:00Z</LastModified></Contents>' for k in keys)
    return io.BytesIO(f'<ListBucketResult xmlns="{archive.NS["s"]}">{items}<IsTruncated>{str(token is not None).lower()}</IsTruncated>{"<NextContinuationToken>"+token+"</NextContinuationToken>" if token else ""}</ListBucketResult>'.encode())

class Helpers(unittest.TestCase):
    def test_pagination_bounds_metadata_duplicates(self):
        urls = []
        responses = iter([page(['2024/05/06/KTLX/KTLX20240506_000000_V06', '2024/05/06/KTLX/KTLX20240506_000001_V06_MDM'], 'a+b'), page(['2024/05/06/KTLX/KTLX20240506_000000_V06', '2024/05/06/KTLX/KTLX20240506_001000_V06'])])
        def fetch(url):
            urls.append(url)
            return next(responses)
        rows = archive.discover('KTLX', archive.utc('2024-05-06T00:00:00Z'), archive.utc('2024-05-06T00:10:00Z'), fetch)
        self.assertEqual(len(rows), 1)
        self.assertIn('continuation-token=a%2Bb', urls[1])

    def test_cross_day_and_timezone(self):
        urls = []
        def fetch(url):
            urls.append(url)
            return page([])
        archive.discover('KTLX', archive.utc('2024-05-05T23:59:00Z'), archive.utc('2024-05-06T00:01:00Z'), fetch)
        self.assertEqual(len(urls), 2)
        self.assertEqual(archive.utc('2024-05-06T01:00:00+01:00'), archive.utc('2024-05-06T00:00:00Z'))
        with self.assertRaises(ValueError): archive.utc('2024-05-06T00:00:00')

    def test_bad_pagination_and_network_failure(self):
        with self.assertRaises(ValueError):
            archive.discover('KTLX', archive.utc('2024-05-06T00:00:00Z'), archive.utc('2024-05-06T00:01:00Z'), lambda url: page([], 'same'))
        def fail(url): raise OSError('network failed')
        with self.assertRaises(OSError):
            archive.discover('KTLX', archive.utc('2024-05-06T00:00:00Z'), archive.utc('2024-05-06T00:01:00Z'), fail)

    def test_download_caps_partial_and_existing(self):
        rows = [{'key': 'KTLX20240506_000000_V06', 'size_bytes': 3, 'url': 'unused'}]
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError): archive.download(rows, directory, 1, 2)
            with self.assertRaises(ValueError): archive.download(rows, directory, 1, 3, lambda url: io.BytesIO(b'ab'))
            self.assertEqual(list(pathlib.Path(directory).iterdir()), [])
            archive.download(rows, directory, 1, 3, lambda url: io.BytesIO(b'abc'))
            with self.assertRaises(ValueError): archive.download(rows, directory, 1, 3)

    def test_masks_are_not_zero(self):
        import numpy as np
        result = field_summary(np.ma.array([[0., 10., 999., np.nan]], mask=[[False, False, True, False]]))
        self.assertEqual(result['valid_gates'], 2)
        self.assertEqual(result['masked_gates'], 2)
        self.assertEqual((result['min'], result['max']), (0., 10.))

    def test_existing_partial_is_preserved(self):
        rows = [{'key': 'KTLX20240506_000000_V06', 'size_bytes': 3, 'url': 'unused'}]
        with tempfile.TemporaryDirectory() as directory:
            partial = pathlib.Path(directory) / 'KTLX20240506_000000_V06.part'
            partial.write_bytes(b'previous download')
            with self.assertRaises(ValueError):
                archive.download(rows, directory, 1, 3, lambda url: io.BytesIO(b'abc'))
            self.assertEqual(partial.read_bytes(), b'previous download')

    def test_download_overrun_and_network_cleanup(self):
        rows = [{'key': 'KTLX20240506_000000_V06', 'size_bytes': 3, 'url': 'unused'}]
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                archive.download(rows, directory, 1, 3, lambda url: io.BytesIO(b'abcd'))
            self.assertEqual(list(pathlib.Path(directory).iterdir()), [])
            def fail(url): raise OSError('network failed')
            with self.assertRaises(OSError):
                archive.download(rows, directory, 1, 3, fail)
            self.assertEqual(list(pathlib.Path(directory).iterdir()), [])

    def test_invalid_windows_station_and_caps(self):
        start = archive.utc('2024-05-06T00:00:00Z')
        for station, end in [('BAD!', archive.utc('2024-05-06T01:00:00Z')), ('KTLX', start), ('KTLX', archive.utc('2024-05-14T00:00:00Z'))]:
            with self.assertRaises(ValueError): archive.discover(station, start, end)
        with self.assertRaises(ValueError): archive.download([], '.', 0, 3)

    def test_all_masked_summary(self):
        import numpy as np
        result = field_summary(np.ma.masked_all((2, 3)))
        self.assertEqual(result['valid_gates'], 0)
        self.assertIsNone(result['min'])
        self.assertIsNone(result['max'])

if __name__ == '__main__': unittest.main()
