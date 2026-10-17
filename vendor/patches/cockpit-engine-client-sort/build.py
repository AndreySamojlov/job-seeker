"""Rebuild the immutable a6 adaptation from the retained upstream a5 wheel."""
import base64
import csv
import hashlib
import io
from pathlib import Path
import zipfile

BASE = Path(__file__).resolve().parent
VENDOR = BASE.parents[1]
INPUT = VENDOR / 'cockpit_engine-0.2.0a5-py3-none-any.whl'
OUTPUT = VENDOR / 'cockpit_engine-0.2.0a6-py3-none-any.whl'
EXPECTED_INPUT = 'aec5195b43cd0ac3d59ceb2d9b8c62202e6874b0515bc6bd6304097d54548630'
assert hashlib.sha256(INPUT.read_bytes()).hexdigest() == EXPECTED_INPUT
with zipfile.ZipFile(INPUT) as source:
    files = {}
    for name in source.namelist():
        if name.endswith('/RECORD'):
            continue
        data = source.read(name)
        target = name.replace('0.2.0a5.dist-info', '0.2.0a6.dist-info')
        if name.endswith('/METADATA'):
            data = data.replace(b'Version: 0.2.0a5', b'Version: 0.2.0a6')
        if name in ['cockpit_engine/web/static/board-table.js', 'cockpit_engine/web/static/board-runtime.js']:
            data = (BASE / Path(name).name).read_bytes()
        files[target] = data
record = 'cockpit_engine-0.2.0a6.dist-info/RECORD'
buffer = io.StringIO(newline='')
writer = csv.writer(buffer, lineterminator='\n')
for name, data in sorted(files.items()):
    digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip('=')
    writer.writerow([name, 'sha256=' + digest, len(data)])
writer.writerow([record, '', ''])
files[record] = buffer.getvalue().encode()
with zipfile.ZipFile(OUTPUT, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as wheel:
    for name, data in sorted(files.items()):
        info = zipfile.ZipInfo(name, date_time=(2026, 10, 16, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o644 << 16
        wheel.writestr(info, data, compresslevel=9)
print(hashlib.sha256(OUTPUT.read_bytes()).hexdigest(), OUTPUT.name)
