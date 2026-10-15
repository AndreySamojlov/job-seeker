import json

import pytest

from job_machine.db import migrate
from job_machine.package import artifacts
from job_machine.package.builder import build_package
from job_machine.package.models import AnswerRecord, PackageInput, ResumeArtifact


def _apply(conn):
    for m in migrate.pending(migrate.discover_migrations("db/migrations"),
                             migrate.applied_migrations(conn)):
        migrate.apply_migration(conn, m)


def test_hash_file(tmp_path):
    p = tmp_path / "cv.pdf"
    p.write_bytes(b"hello-resume")
    import hashlib
    assert artifacts.hash_file(str(p)) == hashlib.sha256(b"hello-resume").hexdigest()


@pytest.mark.db
def test_select_resume_from_artifact(db_schema):
    """select_resume reads the generated artifact row (RG-10: ENV path replaced by DB lookup)."""
    conn, _ = db_schema
    _apply(conn)
    with conn.cursor() as cur:
        cur.execute(
            "insert into vacancy (company, title, canonical_url, ats_family, "
            "vacancy_status, state) values ('Acme','QA Lead','https://acme/apply',"
            "'greenhouse','triaged','triaged') returning vacancy_id")
        vid = cur.fetchone()[0]
        cur.execute(
            "insert into application (vacancy_id, candidate_id, verdict, package_status, state) "
            "values (%s,'andrey-s','apply','none','needs_package') returning application_id", (vid,))
        aid = cur.fetchone()[0]
        cur.execute(
            "insert into artifact (application_id, artifact_type, path_or_uri, content_hash) "
            "values (%s,'resume','/data/resumes/Andrey_QA.pdf','abc123') returning artifact_id",
            (aid,))
        rid = cur.fetchone()[0]
        cur.execute("update application set resume_artifact_id=%s where application_id=%s",
                    (rid, aid))
    conn.commit()
    r = artifacts.select_resume(conn, str(aid))
    assert r.filename == "Andrey_QA.pdf"
    assert r.path == "/data/resumes/Andrey_QA.pdf"
    assert r.content_hash == "abc123"


@pytest.mark.db
def test_select_resume_raises_when_no_resume_bound(db_schema):
    """resume-safety guard: нет сгенерированного резюме → FileNotFoundError (pull обязан был исключить)."""
    conn, _ = db_schema
    _apply(conn)
    with conn.cursor() as cur:
        cur.execute(
            "insert into vacancy (company, title, canonical_url, vacancy_status, state) "
            "values ('Acme','QA Lead','https://acme/apply','triaged','triaged') returning vacancy_id")
        vid = cur.fetchone()[0]
        cur.execute(
            "insert into application (vacancy_id, candidate_id, verdict, package_status, state) "
            "values (%s,'andrey-s','apply','none','needs_package') returning application_id", (vid,))
        aid = cur.fetchone()[0]
    conn.commit()
    with pytest.raises(FileNotFoundError):
        artifacts.select_resume(conn, str(aid))


def test_write_artifacts_creates_files_and_descriptors(tmp_path):
    resume = ResumeArtifact(filename="cv.pdf", path="/x/cv.pdf", content_hash="rh")
    inp = PackageInput(application_id="a1", company="Acme Corp", role="QA Lead",
                       destination_url="https://acme/apply")
    m = build_package(inp, [AnswerRecord(field="English", value="B2", state="locked")], resume)
    descs = artifacts.write_artifacts(str(tmp_path), m, summary_text="СВОДКА")
    by_type = {d["artifact_type"]: d for d in descs}
    assert set(by_type) == {"approval_summary", "manifest"}
    # каталог applications/acme-corp-qa-lead/ создан, файлы на месте
    summ_path = by_type["approval_summary"]["path"]
    assert summ_path.endswith(".md")
    with open(summ_path, encoding="utf-8") as fh:
        assert fh.read() == "СВОДКА"
    with open(by_type["manifest"]["path"], encoding="utf-8") as fh:
        assert json.load(fh)["application_id"] == "a1"
    # content_hash непустой и считается по файлу
    assert len(by_type["manifest"]["content_hash"]) == 64


def _manifest(app_id="a1"):
    from job_machine.package.models import PackageManifest
    return PackageManifest(
        application_id=app_id, company="Acme Co", role="QA Lead",
        destination_url="https://boards.greenhouse.io/acme/jobs/1",
        resume=ResumeArtifact(filename="r.pdf", path="/r.pdf", content_hash="RH"),
        answers=[], consents=[], warnings=[],
        answers_hash="ah", consents_hash="ch", payload_hash="ph")


def test_write_artifacts_unique_dir_per_application(tmp_path):
    d1 = artifacts.write_artifacts(str(tmp_path), _manifest("a1"), "summary A1")
    d2 = artifacts.write_artifacts(str(tmp_path), _manifest("a2"), "summary A2")
    p1 = {d["artifact_type"]: d["path"] for d in d1}
    p2 = {d["artifact_type"]: d["path"] for d in d2}
    assert p1["approval_summary"] != p2["approval_summary"]  # дубль company+role не делит файл
    assert "a1" in p1["manifest"] and "a2" in p2["manifest"]
    with open(p1["approval_summary"], encoding="utf-8") as fh:
        assert fh.read() == "summary A1"  # не перезаписана вторым пакетом


def test_write_artifacts_creates_by_hash_copies(tmp_path):
    import os
    descs = artifacts.write_artifacts(str(tmp_path), _manifest("a1"), "summary text")
    for d in descs:
        ext = os.path.splitext(d["path"])[1]
        copy = os.path.join(os.path.dirname(d["path"]), "by-hash", d["content_hash"] + ext)
        assert os.path.exists(copy)
        with open(copy, encoding="utf-8") as fh, open(d["path"], encoding="utf-8") as orig:
            assert fh.read() == orig.read()


def test_by_hash_copy_survives_regen_overwrite(tmp_path):
    import os
    d_old = artifacts.write_artifacts(str(tmp_path), _manifest("a1"), "OLD approved text")
    old = next(d for d in d_old if d["artifact_type"] == "approval_summary")
    artifacts.write_artifacts(str(tmp_path), _manifest("a1"), "NEW regenerated text")  # тот же app → тот же путь
    copy = os.path.join(os.path.dirname(old["path"]), "by-hash", old["content_hash"] + ".md")
    with open(copy, encoding="utf-8") as fh:
        assert fh.read() == "OLD approved text"  # байты одобрения доступны по hash


def test_write_rebound_artifacts_uniquifies_legacy_dir(tmp_path):
    import os
    legacy_manifest = tmp_path / "manifest.json"
    legacy_manifest.write_text("{}", encoding="utf-8")
    descs = artifacts.write_rebound_artifacts(str(legacy_manifest), _manifest("a9"), "rebound")
    by_type = {d["artifact_type"]: d["path"] for d in descs}
    assert os.path.dirname(by_type["manifest"]) == str(tmp_path / "a9")
    with open(by_type["approval_summary"], encoding="utf-8") as fh:
        assert fh.read() == "rebound"


def test_write_rebound_artifacts_in_place_for_new_layout(tmp_path):
    import os
    app_dir = tmp_path / "acme-co-qa-lead" / "a9"
    app_dir.mkdir(parents=True)
    manifest_path = app_dir / "manifest.json"
    manifest_path.write_text("{}", encoding="utf-8")
    descs = artifacts.write_rebound_artifacts(str(manifest_path), _manifest("a9"), "rebound")
    by_type = {d["artifact_type"]: d["path"] for d in descs}
    assert os.path.dirname(by_type["manifest"]) == str(app_dir)  # без лишней вложенности
