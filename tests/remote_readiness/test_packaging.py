from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_worker_package_is_disabled_and_has_no_published_ports_or_writable_root():
    compose = (ROOT / "deploy" / "remote-readiness" / "compose.yaml").read_text(encoding="utf-8")
    assert 'RWR_ENABLED: "false"' in compose
    assert "ports:" not in compose
    assert "network_mode: none" in compose
    assert "DATABASE_URL" not in compose
    assert "TYPESAFE_API_KEY" not in compose
    assert "secrets:" not in compose
    assert "read_only: true" in compose
    assert 'cap_drop: ["ALL"]' in compose
    assert "no-new-privileges:true" in compose


def test_worker_image_has_an_explicit_runtime_copy_allowlist():
    dockerfile = (ROOT / "deploy" / "remote-readiness" / "Dockerfile").read_text(encoding="utf-8")
    ignore = (ROOT / "deploy" / "remote-readiness" / "Dockerfile.dockerignore").read_text(encoding="utf-8")
    assert "USER 10001:10001" in dockerfile
    assert "COPY ." not in dockerfile
    assert "!src/job_machine/remote_readiness/daemon.py" in ignore
    assert "!src/job_machine/remote_readiness/jev.py" in ignore
    assert "!src/job_machine/remote_readiness/rules.py" in ignore
    assert ".runtime" not in ignore
    assert ".env" not in ignore
