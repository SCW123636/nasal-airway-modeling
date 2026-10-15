"""Read the exact installed Debian source version; extract only scheme source files."""
import hashlib
import json
from pathlib import Path
import tarfile
import urllib.request

OUT = Path(__file__).resolve().parent
CACHE = OUT / 'source_cache'
CACHE.mkdir(exist_ok=True)
BASE = 'https://deb.debian.org/debian/pool/main/o/openfoam/'
files = {'openfoam_1912.200626.orig.tar.bz2':'c75ca0f04cc4f49708296c1926cbde9d0138b3fef298fed54270dfe29e2df404',
         'openfoam_1912.200626-1.debian.tar.xz':'87a9059001b2f3a58d6bae3fb69284b124974ea39bc6881ae16623e482a367e0'}
records = []
for name, expected in files.items():
    path = CACHE / name
    if not path.exists():
        temp = path.with_suffix(path.suffix + '.part')
        with urllib.request.urlopen(BASE + name, timeout=15) as response, temp.open('xb') as output:
            while True:
                block = response.read(1024*1024)
                if not block:
                    break
                output.write(block)
        assert hashlib.sha256(temp.read_bytes()).hexdigest() == expected, 'archive SHA mismatch'
        temp.replace(path)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == expected
    copied = []
    with tarfile.open(path, 'r:*') as archive:
        for member in archive:
            if not member.isfile():
                continue
            keep = member.name.endswith(('/limitedSnGrad/limitedSnGrad.H', '/limitedSnGrad/limitedSnGrad.C',
                                         '/gaussLaplacianScheme/gaussLaplacianScheme.H', '/gaussLaplacianScheme/gaussLaplacianScheme.C'))
            keep |= name.endswith('.xz') and ('debian/patches/' in member.name or member.name.endswith('debian/changelog'))
            if keep:
                data = archive.extractfile(member).read()
                destination = OUT / 'exact_1912_source' / member.name
                destination.parent.mkdir(parents=True, exist_ok=True)
                if destination.exists():
                    assert destination.read_bytes() == data
                else:
                    destination.write_bytes(data)
                copied.append({'member':member.name, 'file':str(destination), 'sha256':hashlib.sha256(data).hexdigest()})
    records.append({'url':BASE + name, 'sha256':expected, 'descriptor':'debian-1912.dsc',
                    'version':'1912.200626-1', 'descriptor_signature_independently_checked':False,
                    'archive_bytes':path.stat().st_size, 'extracted':copied})
(OUT / 'exact-source-index.json').write_text(json.dumps(records,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(records, ensure_ascii=False), flush=True)
