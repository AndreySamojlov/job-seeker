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
    assert "COPY src/job_machine/audit.py /app/src/job_machine/audit.py" in dockerfile
    assert "COPY src/job_machine/guards/base.py /app/src/job_machine/guards/base.py" in dockerfile
    assert "COPY src/job_machine/discovery/store.py /app/src/job_machine/discovery/store.py" in dockerfile
    assert ".runtime" not in ignore
    assert ".env" not in ignore


def test_worker_image_pins_pydantic_required_by_greenhouse_adapter():
    dockerfile = (ROOT / "deploy" / "remote-readiness" / "Dockerfile").read_text(encoding="utf-8")
    requirements = (ROOT / "deploy" / "remote-readiness" / "requirements.lock").read_text(encoding="utf-8")
    assert "'pydantic==2.13.4'" in dockerfile
    for requirement in (
        "annotated-types==0.7.0",
        "pydantic==2.13.4",
        "pydantic-core==2.46.4",
        "typing-inspection==0.4.2",
    ):
        assert requirement in requirements


def test_r5_hotfix_only_overlays_the_approved_stale_path():
    dockerfile = (ROOT / "deploy" / "remote-readiness" / "Dockerfile.r5-hotfix").read_text(encoding="utf-8")
    assert "FROM job-machine/rwr-worker:rwr-20261017-r4" in dockerfile.splitlines()
    assert "COPY --chown=10001:10001 src/job_machine/remote_readiness/intake_store.py" in dockerfile
    assert "USER 10001:10001" in dockerfile
