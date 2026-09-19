import json
import re
import subprocess
import sys
import zipfile

from control import ROOT


def verify_apk(apk, aapt):
    expected = json.loads((ROOT / '.github/release.json').read_text())
    output = subprocess.check_output([aapt, 'dump', 'badging', apk], encoding='utf-8', errors='replace')
    package = re.search(r"package: name='([^']+)' versionCode='(\d+)'", output)
    if not package or package[1] != expected['applicationId'] or int(package[2]) != expected['build']:
        raise ValueError('APK package/build does not match release manifest')
    with zipfile.ZipFile(apk) as archive:
        for name in ('libapp.so', 'libflutter.so', 'libclash.so', 'librust_api.so'):
            if f'lib/arm64-v8a/{name}' not in archive.namelist():
                raise ValueError(f'Missing ARM64 runtime {name}')
    print('Verified APK package, build number and ARM64 runtimes')


if __name__ == '__main__':
    verify_apk(sys.argv[1], sys.argv[2])
