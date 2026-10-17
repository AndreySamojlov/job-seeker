"""Build the immutable Job Seeker consumer wheel a7 from pinned Engine a6."""
import base64
import csv
import hashlib
import io
from pathlib import Path
import zipfile

BASE = Path(__file__).resolve().parent
VENDOR = BASE.parents[1]
INPUT = VENDOR / "cockpit_engine-0.2.0a6-py3-none-any.whl"
OUTPUT = VENDOR / "cockpit_engine-0.2.0a7-py3-none-any.whl"
EXPECTED_INPUT = "f23305d541535c7043aab30441685552b474b462078cd30bfd9519624f84616c"
PATCHED = {
    "cockpit_engine/web/static/board-table.js": BASE / "board-table.js",
    "cockpit_engine/web/static/board-runtime.js": BASE / "board-runtime.js",
}

def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

if sha256(INPUT.read_bytes()) != EXPECTED_INPUT:
    raise SystemExit("a6 input wheel SHA-256 mismatch")
files: dict[str, bytes] = {}
with zipfile.ZipFile(INPUT) as source:
    for name in source.namelist():
        if name.endswith("/RECORD"):
            continue
        data = source.read(name)
        target = name.replace("0.2.0a6.dist-info", "0.2.0a7.dist-info")
        if name.endswith("/METADATA"):
            old = b"Version: 0.2.0a6"
            if data.count(old) != 1:
                raise SystemExit("unexpected a6 METADATA version field")
            data = data.replace(old, b"Version: 0.2.0a7")
        if name in PATCHED:
            data = PATCHED[name].read_bytes()
        files[target] = data
record = "cockpit_engine-0.2.0a7.dist-info/RECORD"
buffer = io.StringIO(newline="")
writer = csv.writer(buffer, lineterminator="\n")
for name, data in sorted(files.items()):
    digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip("=")
    writer.writerow([name, "sha256=" + digest, len(data)])
writer.writerow([record, "", ""])
files[record] = buffer.getvalue().encode("utf-8")
with zipfile.ZipFile(OUTPUT, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as wheel:
    for name, data in sorted(files.items()):
        info = zipfile.ZipInfo(name, date_time=(2026, 10, 16, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o644 << 16
        wheel.writestr(info, data, compresslevel=9)
print(sha256(OUTPUT.read_bytes()), OUTPUT.name)
