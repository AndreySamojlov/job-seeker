"""Create the immutable a9 board wheel with the accepted table link style."""
from __future__ import annotations

import base64
import csv
import hashlib
import io
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[3]
VENDOR = ROOT / "vendor"
INPUT = VENDOR / "cockpit_engine-0.2.0a8-py3-none-any.whl"
OUTPUT = VENDOR / "cockpit_engine-0.2.0a9-py3-none-any.whl"
STYLES = Path(__file__).with_name("styles.css")
BOARD_S3 = ROOT / "vendor/patches/cockpit-engine-board-s3"
INPUT_SHA256 = "263e176692debe4a41dbe0a4bec6118946e6b37af1b88dce3901ba0160f00fc4"
STYLES_SHA256 = "6358e81a89855205c07dd90171ff7f7d7e796c670939099328a12546e92afb1d"
OLD_VERSION = "0.2.0a8"
NEW_VERSION = "0.2.0a9"
DIST_INFO = f"cockpit_engine-{OLD_VERSION}.dist-info"
NEW_DIST_INFO = f"cockpit_engine-{NEW_VERSION}.dist-info"
STYLES_PATH = "cockpit_engine/web/static/styles.css"
PATCHED_ASSETS = {
    "cockpit_engine/web/static/board-runtime.js": BOARD_S3 / "board-runtime.js",
    "cockpit_engine/web/static/board-table.js": BOARD_S3 / "board-table.js",
}


def digest(data: bytes) -> str:
    return "sha256=" + base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip("=")


def main() -> None:
    if hashlib.sha256(INPUT.read_bytes()).hexdigest() != INPUT_SHA256:
        raise SystemExit("Input wheel hash mismatch; refusing to adapt a different base")
    styles = STYLES.read_bytes()
    if hashlib.sha256(styles).hexdigest() != STYLES_SHA256:
        raise SystemExit("Accepted stylesheet hash mismatch; refusing to build")
    if OUTPUT.exists():
        raise SystemExit(f"Refusing to overwrite immutable artifact: {OUTPUT}")

    with zipfile.ZipFile(INPUT) as source:
        members = {name: source.read(name) for name in source.namelist()}
    members[STYLES_PATH] = styles
    for name, path in PATCHED_ASSETS.items():
        members[name] = path.read_bytes()
    metadata = f"{DIST_INFO}/METADATA"
    old_line = f"Version: {OLD_VERSION}".encode()
    if members[metadata].count(old_line) != 1:
        raise SystemExit("Expected one package version line in pinned wheel metadata")
    members[metadata] = members[metadata].replace(old_line, f"Version: {NEW_VERSION}".encode())

    renamed = {
        name.replace(DIST_INFO, NEW_DIST_INFO, 1)
        if name.startswith(DIST_INFO + "/") else name: content
        for name, content in members.items()
    }
    record = f"{NEW_DIST_INFO}/RECORD"
    rows = []
    for name, content in sorted(renamed.items()):
        rows.append((name, "" if name == record else digest(content),
                     "" if name == record else str(len(content))))
    buffer = io.StringIO(newline="")
    csv.writer(buffer, lineterminator="\n").writerows(rows)
    renamed[record] = buffer.getvalue().encode("utf-8")

    with zipfile.ZipFile(OUTPUT, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as target:
        for name, content in sorted(renamed.items()):
            info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            target.writestr(info, content)

    with zipfile.ZipFile(OUTPUT) as built:
        contents = {name: built.read(name) for name in built.namelist()}
    if contents[STYLES_PATH] != styles:
        raise SystemExit("Output stylesheet mismatch")
    if contents["cockpit_engine/web/static/board-runtime.js"] != members["cockpit_engine/web/static/board-runtime.js"]:
        raise SystemExit("RWR board runtime was unexpectedly changed")
    if contents["cockpit_engine/web/static/board-table.js"] != members["cockpit_engine/web/static/board-table.js"]:
        raise SystemExit("RWR board table was unexpectedly changed")
    rows = csv.reader(io.StringIO(contents[record].decode("utf-8")))
    records = {row[0]: row[1:] for row in rows}
    if set(records) != set(contents):
        raise SystemExit("Wheel RECORD file list does not match archive")
    for name, content in contents.items():
        file_hash, size = records[name]
        if name == record:
            if file_hash or size:
                raise SystemExit("Wheel RECORD must not hash itself")
        elif file_hash != digest(content) or size != str(len(content)):
            raise SystemExit(f"Wheel RECORD mismatch for {name}")
    print(f"wheel_sha256={hashlib.sha256(OUTPUT.read_bytes()).hexdigest()}")
    print(f"styles_sha256={hashlib.sha256(styles).hexdigest()}")


if __name__ == "__main__":
    main()
