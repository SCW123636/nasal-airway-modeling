"""Vendor a pinned official npm Three.js release for local, offline viewing."""
import hashlib
import io
import json
from pathlib import Path
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
VERSION = '0.180.0'
URL = f'https://registry.npmjs.org/three/-/three-{VERSION}.tgz'


def main():
    dest = ROOT/'work'/'07_cfd_pipeline'/'viewer'/'vendor'
    dest.mkdir(parents=True, exist_ok=True)
    wanted = {'package/build/three.module.js': 'three.module.js',
              'package/build/three.core.js': 'three.core.js',
              'package/examples/jsm/controls/OrbitControls.js': 'OrbitControls.js',
              'package/LICENSE': 'THREE_LICENSE.txt'}
    receipt_path = dest/'source.json'
    if receipt_path.is_file():
        receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
        if receipt.get('version') == VERSION and all((dest/name).is_file() and
                hashlib.sha256((dest/name).read_bytes()).hexdigest() == receipt['files_sha256'].get(name)
                for name in wanted.values()):
            print('Pinned offline assets already verified')
            return
    with urllib.request.urlopen(URL, timeout=90) as response:
        content = response.read()
    with tarfile.open(fileobj=io.BytesIO(content), mode='r:gz') as package:
        for source, name in wanted.items():
            item = package.getmember(source)
            if not item.isfile():
                raise ValueError('Expected a regular package file: '+source)
            (dest/name).write_bytes(package.extractfile(item).read())
    receipt = {'package':'three', 'version':VERSION, 'source':URL,
               'tarball_sha256':hashlib.sha256(content).hexdigest(),
               'files_sha256': {n: hashlib.sha256((dest/n).read_bytes()).hexdigest() for n in wanted.values()},
               'network_required_at_view_time':False}
    receipt_path.write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()
