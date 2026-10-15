"""Резюме-хеш, выбор резюме, запись артефактов пакета под applications/<company>-<role>/.

Резюме не копируется (resume safety §3 — без drift): привязка по абсолютному пути + content_hash.
Записываются disclosed-summary.ru.md (artifact_type=approval_summary) и manifest.json (manifest)."""
import hashlib
import os
import re
import shutil

from job_machine.package.models import PackageManifest, ResumeArtifact


def hash_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def select_resume(conn, application_id: str) -> ResumeArtifact:
    """Привязываемое резюме — сгенерированный артефакт заявки (application.resume_artifact_id).

    Резюме генерируется отдельным resume-воркером ДО сборки пакета; пакет лишь привязывает его
    (resume safety §3 — без подмены/копирования). Нет артефакта → пакет не должен был тянуть заявку.
    """
    with conn.cursor() as cur:
        cur.execute("select ar.path_or_uri, ar.content_hash from artifact ar "
                    "join application a on a.resume_artifact_id = ar.artifact_id "
                    "where a.application_id=%s", (application_id,))
        row = cur.fetchone()
    if row is None:
        raise FileNotFoundError(f"нет сгенерированного резюме для заявки {application_id}")
    return ResumeArtifact(filename=os.path.basename(row[0]), path=row[0], content_hash=row[1])


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s or "x"


def _write(path: str, text: str) -> dict:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return {"path": path, "content_hash": hash_file(path)}


def write_artifacts(base_dir: str, manifest: PackageManifest, summary_text: str) -> list[dict]:
    slug = f"{_slug(manifest.company)}-{_slug(manifest.role)}"
    # <slug>/<application_id>/ — дубли company+role не делят директорию (аудит 02.07)
    out_dir = os.path.join(base_dir, slug, manifest.application_id)
    return _write_package_files(out_dir, manifest, summary_text)


def write_rebound_artifacts(manifest_path: str, manifest: PackageManifest,
                            summary_text: str) -> list[dict]:
    """Артефакты ребинда destination (fill-этап) — в директорию заявки.

    Legacy-раскладка (общая слаг-директория без application_id в пути)
    уникализируется поддиректорией — соседние заявки не затираются."""
    out_dir = os.path.dirname(os.path.abspath(manifest_path))
    if os.path.basename(out_dir) != manifest.application_id:
        out_dir = os.path.join(out_dir, manifest.application_id)
    return _write_package_files(out_dir, manifest, summary_text)


def _write_package_files(out_dir: str, manifest: PackageManifest,
                         summary_text: str) -> list[dict]:
    os.makedirs(out_dir, exist_ok=True)
    summ = _write(os.path.join(out_dir, "disclosed-summary.ru.md"), summary_text)
    man = _write(os.path.join(out_dir, "manifest.json"),
                 manifest.model_dump_json(indent=2))
    _byhash_copy(out_dir, summ)
    _byhash_copy(out_dir, man)
    return [
        {"artifact_type": "approval_summary", **summ},
        {"artifact_type": "manifest", **man},
    ]


def _byhash_copy(out_dir: str, desc: dict) -> None:
    """Content-addressed копия: байты, раскрытые владельцу, остаются доступны по
    hash даже после regen-перезаписи основного файла. Существующую копию не трогаем."""
    ext = os.path.splitext(desc["path"])[1]
    bh_dir = os.path.join(out_dir, "by-hash")
    os.makedirs(bh_dir, exist_ok=True)
    dst = os.path.join(bh_dir, desc["content_hash"] + ext)
    if not os.path.exists(dst):
        shutil.copyfile(desc["path"], dst)
