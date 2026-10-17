import hashlib
from pathlib import Path
import zipfile


ROOT = Path(__file__).resolve().parents[2]


def test_board_image_pins_combined_engine_a9_wheel_and_preserves_link_style():
    dockerfile = (ROOT / "deploy" / "board" / "Dockerfile").read_text(encoding="utf-8")
    wheel = ROOT / "vendor" / "cockpit_engine-0.2.0a9-py3-none-any.whl"
    expected_base = (
        "job-machine/board:jev-s4-20261016-r1@sha256:"
        "a05274af6da97675e12022bae91133346b8acc138aa51a91ca833be0e51890c6"
    )
    expected_wheel_hash = "b1e4883ac1f636a8b09ae7bb1fdfedf1e630b4908d34ec889a7ccae1ba5c3916"

    assert dockerfile.startswith(f"FROM {expected_base}\n")
    assert "cockpit_engine-0.2.0a9-py3-none-any.whl" in dockerfile
    assert "COPY vendor/cockpit_engine-0.2.0a9-py3-none-any.whl /tmp/engine.whl" in dockerfile
    assert "cockpit_engine-0.2.0a5" not in dockerfile
    assert hashlib.sha256(wheel.read_bytes()).hexdigest() == expected_wheel_hash
    assert expected_wheel_hash in dockerfile
    assert "COPY src/job_machine/board/ /app/src/job_machine/board/" in dockerfile
    assert "COPY config/sources.json /app/config/sources.json" in dockerfile
    with zipfile.ZipFile(wheel) as package:
        styles = package.read("cockpit_engine/web/static/styles.css").decode("utf-8")
        runtime = package.read("cockpit_engine/web/static/board-runtime.js").decode("utf-8")
        table = package.read("cockpit_engine/web/static/board-table.js").decode("utf-8")
    assert ".tblwrap.tbleng table td a" in styles
    assert "color: var(--ink); text-decoration-line: underline" in styles
    assert "text-decoration-style: solid" in styles
    assert ".tblissue { text-decoration: underline dotted" in styles
    assert "client_sort" in runtime
    assert "boardTablePage" in table


def test_board_image_context_allows_only_deployment_inputs():
    ignore = (ROOT / "deploy" / "board" / "Dockerfile.dockerignore").read_text(encoding="utf-8")
    dockerfile = (ROOT / "deploy" / "board" / "Dockerfile").read_text(encoding="utf-8")
    assert [line for line in ignore.splitlines() if line and not line.startswith("#")] == [
        "**",
        "!deploy/",
        "deploy/*",
        "!deploy/board/",
        "deploy/board/*",
        "!deploy/board/Dockerfile",
        "!vendor/",
        "vendor/*",
        "!vendor/cockpit_engine-0.2.0a9-py3-none-any.whl",
        "!src/",
        "src/*",
        "!src/job_machine/",
        "src/job_machine/*",
        "!src/job_machine/board/",
        "src/job_machine/board/*",
        "!src/job_machine/board/*.py",
        "!config/",
        "config/*",
        "!config/sources.json",
    ]
    assert "COPY ." not in dockerfile
