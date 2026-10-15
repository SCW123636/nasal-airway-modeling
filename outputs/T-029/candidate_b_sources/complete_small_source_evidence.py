"""Fetch only the exact-version scheme selection/solver source missing locally."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import urllib.request

OUT = Path(__file__).resolve().parent
ROOT = 'https://salsa.debian.org/science-team/openfoam/-/raw/debian/1912.200626-1/'
FILES = {
    'salsa_laplacianScheme.H': 'src/finiteVolume/finiteVolume/laplacianSchemes/laplacianScheme/laplacianScheme.H',
    'salsa_gaussLaplacianScheme.H': 'src/finiteVolume/finiteVolume/laplacianSchemes/gaussLaplacianScheme/gaussLaplacianScheme.H',
    'salsa_fvcSnGrad.C': 'src/finiteVolume/finiteVolume/fvc/fvcSnGrad.C',
    'salsa_simpleFoam_pEqn.H': 'applications/solvers/incompressible/simpleFoam/pEqn.H',
    'salsa_simpleFoam_UEqn.H': 'applications/solvers/incompressible/simpleFoam/UEqn.H',
    'salsa_linearViscousStress.C': 'src/TurbulenceModels/turbulenceModels/linearViscousStress/linearViscousStress.C',
}


def fetch(item):
    name, relative = item
    url = ROOT + relative
    target = OUT / name
    if target.exists():
        data = target.read_bytes()
    else:
        request = urllib.request.Request(url, headers={'User-Agent': 'nasal-cfd-local-source-audit/1.0'})
        with urllib.request.urlopen(request, timeout=30) as response:
            data = response.read(100000)
        marker = {
            'salsa_simpleFoam_pEqn.H': b'fvm::laplacian',
            'salsa_simpleFoam_UEqn.H': b'divDevReff',
        }.get(name, b'Foam')
        if marker not in data or b'<html' in data.lower() or len(data) < 100:
            raise ValueError('response is not the expected C++ source: ' + url)
        target.write_bytes(data)
    return {'url': url, 'path': name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


if __name__ == '__main__':
    records = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        for record in pool.map(fetch, FILES.items()):
            records.append(record)
    for name in ('salsa_limitedSnGrad.H', 'salsa_limitedSnGrad.C', 'salsa_gaussLaplacianScheme.C'):
        path = OUT / name
        data = path.read_bytes()
        records.append({'url': ROOT + {
            'salsa_limitedSnGrad.H': 'src/finiteVolume/finiteVolume/snGradSchemes/limitedSnGrad/limitedSnGrad.H',
            'salsa_limitedSnGrad.C': 'src/finiteVolume/finiteVolume/snGradSchemes/limitedSnGrad/limitedSnGrad.C',
            'salsa_gaussLaplacianScheme.C': 'src/finiteVolume/finiteVolume/laplacianSchemes/gaussLaplacianScheme/gaussLaplacianScheme.C',
        }[name], 'path': name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
    result = {'tag': 'debian/1912.200626-1', 'source_records': records,
              'scope': 'exact Debian package-tag source; no claim of a complete local source tree or full archive verification'}
    target = OUT / 'exact-small-source-index.json'
    if target.exists():
        assert json.loads(target.read_text(encoding='utf-8')) == result
    else:
        target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))
