import json
import re
import subprocess
import sys
import zipfile

from control import ROOT, verify_native_identity


def verify_apk(apk, aapt):
    expected = json.loads((ROOT / '.github/release.json').read_text())
    output = subprocess.check_output([aapt, 'dump', 'badging', apk], encoding='utf-8', errors='replace')
    package = re.search(r"package: name='([^']+)' versionCode='(\d+)' versionName='([^']+)'", output)
    if not package:
        raise ValueError('APK badging is missing package, versionCode or versionName')
    verify_native_identity(expected, package[1], int(package[2]), package[3])
    with zipfile.ZipFile(apk) as archive:
        for name in ('libapp.so', 'libflutter.so', 'libclash.so', 'librust_api.so'):
            if f'lib/arm64-v8a/{name}' not in archive.namelist():
                raise ValueError(f'Missing ARM64 runtime {name}')
    print(f'Verified APK package, build {package[2]} and versionName {package[3]} with ARM64 runtimes')


if __name__ == '__main__':
    verify_apk(sys.argv[1], sys.argv[2])
