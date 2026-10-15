"""[SAFETY] Контур честности генерации (§3). Детерминированно, без LLM.

Перефразировка (придёт от LLM в n8n) откатывается к ДОСЛОВНОМУ source_text, если вносит:
  - число, которого нет в источнике (text+metric);
  - запрещённый токен (linux/jenkins/javascript/c1/ci-cd pipeline);
  - НОВУЮ именованную сущность — Capitalized-слово в СЕРЕДИНЕ предложения, ALLCAPS-аббревиатуру
    или известный tech-токен, которого нет в источнике. Это блокирует выдуманные
    инструменты/работодателей/технологии (Kubernetes, AWS, Salesforce, ...).
Отсутствие фразинга → source_text. Так LLM не может протащить новый ФАКТ/цифру/инструмент.

Заглавная буква в начале предложения — грамматика, не сущность: её не считаем именем
собственным (иначе любой нормальный перефраз «Owned ...» отвергался бы).

Остаточный риск (известный, задокументирован): строчная РОДОВАЯ выдумка без чисел и имён
собственных («managed a team of engineers across regions») детерминированно не ловится —
митигируется системным промптом n8n («только факты из source») и тем, что дефолт — дословный
источник. Семантическую проверку сюда не тянем — это снова LLM, что ломает «детерминизм внизу».
"""
import re

from job_machine.resume.models import ResumePhrasing, ResumeSelection

_NUM = re.compile(r"\d[\d,.]*")
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9+/.#-]*")
_FORBIDDEN = ("linux", "jenkins", "javascript", " c1", "ci/cd pipeline")
# Известные технологии/платформы: ловим выдуманное имя инструмента, даже если оно строчное.
_TECH = {
    "kubernetes", "k8s", "aws", "azure", "gcp", "salesforce", "terraform", "ansible",
    "openshift", "snowflake", "databricks", "hadoop", "spark", "tableau", "sap",
    "servicenow", "workday", "mongodb", "redis", "rabbitmq", "react", "angular",
    "vue", "django", "flask", "spring", "dotnet", "golang", "kotlin", "scala",
}


def _numbers(text: str) -> set[str]:
    return {m.replace(",", "").rstrip(".") for m in _NUM.findall(text or "")}


def _source_words(text: str) -> set[str]:
    return {m.group(0).lower() for m in _WORD.finditer(text or "")}


def _introduces_new_entity(phrased: str, source_words: set[str]) -> bool:
    """True, если фразинг вносит именованную сущность (Capitalized в середине предложения,
    ALLCAPS-аббревиатура или tech-токен), которой нет в источнике."""
    text = phrased or ""
    for m in _WORD.finditer(text):
        tok = m.group(0)
        low = tok.lower()
        prefix = text[:m.start()].rstrip()
        at_sentence_start = prefix == "" or prefix[-1] in ".!?:;"
        is_acronym = len(tok) >= 2 and tok.isupper()
        is_proper = (not at_sentence_start and len(tok) >= 2
                     and tok[0].isupper() and not tok.isupper())
        is_tech = low in _TECH
        if (is_acronym or is_proper or is_tech) and low not in source_words:
            return True
    return False


def _accept(phrased: str, source_text: str, source_metric: str) -> bool:
    src = _numbers(source_text) | _numbers(source_metric)
    if not _numbers(phrased) <= src:
        return False
    low = phrased.lower()
    if any(tok in low for tok in _FORBIDDEN):
        return False
    if _introduces_new_entity(phrased, _source_words(f"{source_text} {source_metric}")):
        return False
    return True


def verify(selection: ResumeSelection, phrasing: ResumePhrasing) -> dict[str, str]:
    """aid -> финальный текст буллета (перефраз если безопасен, иначе source_text)."""
    by_aid = {b.aid: b for p in selection.positions for b in p.bullets}
    phrased = {pb.aid: pb.phrased_text for pb in phrasing.bullets}
    out: dict[str, str] = {}
    for aid, b in by_aid.items():
        cand = phrased.get(aid)
        if cand and _accept(cand, b.source_text, b.source_metric):
            out[aid] = cand.strip()
        else:
            out[aid] = b.source_text
    return out
