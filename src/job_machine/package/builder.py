"""Детерминированная сборка пакета (контур честности §3).

ТОЛЬКО locked-факты раскрываются как передаваемые ответы и входят в payload_hash.
blocked-факты (work auth, salary, sponsorship, German) — раскрытые warnings, НЕ передаются.
optional-policy — consents (decline/blank). Никакого вымысла, никакого I/O, никакого LLM.
"""
from job_machine.package import hashing
from job_machine.package.models import (
    DisclosedAnswer, DisclosedConsent, PackageInput, PackageManifest,
    ResumeArtifact, UnresolvedFact,
)


def build_package(inp: PackageInput, answers, resume: ResumeArtifact) -> PackageManifest:
    disclosed: list[DisclosedAnswer] = []
    consents: list[DisclosedConsent] = []
    warnings: list[UnresolvedFact] = []
    for a in answers:
        if a.state == "locked":
            disclosed.append(DisclosedAnswer(field=a.field, value=a.value))
        elif a.state == "optional-policy":
            consents.append(DisclosedConsent(field=a.field, decision=a.value))
        else:  # blocked — раскрываем как warning, НЕ передаём
            warnings.append(UnresolvedFact(field=a.field, rule=a.rule))
    return PackageManifest(
        application_id=inp.application_id, company=inp.company, role=inp.role,
        destination_url=inp.destination_url, resume=resume,
        answers=disclosed, consents=consents, warnings=warnings,
        fit_summary=inp.fit_summary, hard_requirements=inp.hard_requirements,
        material_unknowns=inp.material_unknowns, overclaim_risks=inp.overclaim_risks,
        answers_hash=hashing.answers_hash(disclosed),
        consents_hash=hashing.consents_hash(consents),
        payload_hash=hashing.payload_hash(
            inp.destination_url, resume.content_hash, disclosed, consents),
    )


def rebind_destination(manifest: PackageManifest, final_url: str) -> PackageManifest:
    """Ребинд пакета на фактический URL подачи (после редиректов, fill-этап).

    Меняются ТОЛЬКО destination_url и payload_hash; answers/consents/resume
    неизменны — approval после ребинда биндится к реальному destination."""
    return manifest.model_copy(update={
        "destination_url": final_url,
        "payload_hash": hashing.payload_hash(
            final_url, manifest.resume.content_hash,
            manifest.answers, manifest.consents),
    })
