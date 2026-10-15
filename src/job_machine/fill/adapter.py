"""Детерминированный ATS-маппинг disclosed answers → поля формы (без LLM, без сети).

Принцип честности: на вход приходят ТОЛЬКО disclosed answers (locked) из manifest пакета.
Blocked-факты (work authorization, salary, sponsorship, German) физически отсутствуют —
поэтому любое обязательное поле, их спрашивающее, не находит значения и попадает в
unmatched_required → доменный блокер mandatory_unknown (стоп владельцу). Consent-чекбоксы
не проставляются автоматически, ЗА ИСКЛЮЧЕНИЕМ стоячего согласия владельца — по стабильному
имени поля (_STANDING_CONSENT_NAMES) или по тексту question-level label для single-option
company-custom вопросов (looks_like_standing_label_consent, см. consent.py).
"""

import re

from job_machine.browser.schema import FormSchema
from job_machine.consent import (
    looks_like_consent,
    looks_like_decline_option,
    looks_like_standing_label_consent,
)
from job_machine.fill.models import MappingResult

_GH_FIRST = ("[first_name]", "first_name")
_GH_LAST = ("[last_name]", "last_name")

# Fallback names assigned by inspect.py when an element has no name/id attribute.
# These are JS-managed widget internals (e.g. ITI dial-code, Greenhouse answer mirrors)
# that cannot be targeted by [name=] selectors — skip them from required checks.
_AUTO_FIELD_RE = re.compile(r"^field_\d+$")

# "Which is your preferred location for this role?" style company-custom checkbox
# groups (владелец, 2026-07-24) — узкий allowlist по question-level group_label, не
# fuzzy: шире значило бы риск подставить дефолт не туда, где реально спрашивают локацию.
_LOCATION_QUESTION_HINTS = (
    "preferred location",
    "which location",
)


def _looks_like_location_question(group_label) -> bool:
    low = (group_label or "").lower()
    return any(h in low for h in _LOCATION_QUESTION_HINTS)


# Allowlist known-safe question shapes for the general "Other" fallback (владелец,
# 2026-07-24; сужено code-review 2026-07-24: изначальная permissive-with-denylist
# версия рисковала сработать на blocked-факте — work authorization/sponsorship/German
# level с опцией "Other" тоже проходили бы demographic-гейт). Тот же паттерн, что и
# _LOCATION_QUESTION_HINTS: узкий allowlist по question-level group_label — шире
# значило бы риск подставить "Other" туда, где это на самом деле честный blocked-факт
# (§3 docstring модуля: work authorization/salary/sponsorship/German — НЕ авто).
_OTHER_FALLBACK_QUESTION_HINTS = (
    "current location",
    "how did you hear",
    "how did you find",
)


def _looks_like_other_fallback_eligible_question(group_label) -> bool:
    low = (group_label or "").lower()
    return any(h in low for h in _OTHER_FALLBACK_QUESTION_HINTS)


# Гейт для общего "Other"-фолбэка: demographic/EEO-группы исключаются целиком — там
# "Other" может быть настоящей self-ID категорией (напр. gender), а не "ничего из
# перечисленного не подошло". Проверяем и group_label, и КАЖДЫЙ sibling-label в
# группе — список реальных категорий/тем, встречающихся в EEO/self-ID блоках
# Greenhouse. Defense-in-depth поверх allowlist выше (который уже не пускает сюда
# gender/orientation-вопросы на практике, раз их group_label не про location/source).
_DEMOGRAPHIC_HINTS = (
    "male", "female", "non-binary", "nonbinary", "genderqueer", "transgender",
    "race", "ethnic", "hispanic", "latino", "latina", "black or african american",
    "asian", "native american", "native hawaiian", "pacific islander",
    "veteran", "disability", "lgbtq", "gender", "sex", "orientation", "identity",
)


def _looks_like_demographic_group(opts) -> bool:
    labels = [opts[0].group_label or ""] + [o.label or "" for o in opts]
    return any(h in label.lower() for label in labels for h in _DEMOGRAPHIC_HINTS)


# Стоячие согласия владельца — проставляются автоматически (§3, 2026-07-01).
# Только GDPR/privacy согласия на обработку ПДн; demographic / work-auth — НЕ авто.
_STANDING_CONSENT_NAMES: frozenset[str] = frozenset({
    "gdpr_demographic_data_consent_given",
    "gdpr_processing_consent_given",
})


def _norm(text: str) -> str:
    """Нормализация для сопоставления: lower + только буквы/цифры/пробел, схлоп пробелов."""
    s = re.sub(r"[^a-z0-9 ]+", " ", (text or "").lower())
    return re.sub(r"\s+", " ", s).strip()


def _answers_index(answers):
    return {_norm(a.field): a.value for a in answers}


def _split_name(full: str):
    parts = (full or "").split()
    if not parts:
        return "", ""
    return parts[0], " ".join(parts[1:])


def _name_has(name: str, needles) -> bool:
    low = name.lower()
    return any(n in low for n in needles)


def _candidate_value(field, idx):
    """Значение-кандидат для поля по имени (GH) или нормализованному label. None если нет."""
    name = field.name or ""
    full = idx.get(_norm("Full name"), "")
    first, last = _split_name(full)
    if _name_has(name, _GH_FIRST):
        return first or None
    if _name_has(name, _GH_LAST):
        return last or None
    if _name_has(name, ("email",)):
        return idx.get(_norm("Email"))
    if _name_has(name, ("phone",)):
        return idx.get(_norm("Phone"))
    # Точное совпадение normalized field.name с disclosed-ключом — до label-матчинга.
    # Кастомные react-select вопросы (job-boards.greenhouse.io) часто не имеют
    # <label for=id>, поэтому field.label пуст; единственный стабильный идентификатор —
    # буквальный DOM id/name (напр. "question_67943985"), по которому владелец уже мог
    # заранее ответить через set_application_answers. Точный (не подстрочный) матч —
    # риска неоднозначности нет, в отличие от label-substring ниже (аудит Adyen/Addepar
    # submit_blocked, 23.07).
    name_n = _norm(name)
    if name_n and name_n in idx:
        return idx[name_n]
    label_n = _norm(field.label or "")
    if not label_n:
        return None
    # Точное совпадение нормализованного label с vault-полем — высший приоритет.
    if label_n in idx:
        return idx[label_n]
    # Иначе подстрочный матч, НО только если он ОДНОЗНАЧЕН (ровно один кандидат). При
    # нескольких подходящих vault-полях не угадываем — возвращаем None, поле уйдёт в
    # unmatched_required (review MAJOR-1: иначе first-hit по неупорядоченному dict мог бы
    # привязать значение к семантически другому полю — риск вымысла §3).
    candidates = [
        value for vault_norm, value in idx.items()
        if vault_norm and (vault_norm in label_n or label_n in vault_norm)
    ]
    if len(candidates) == 1:
        return candidates[0]
    return None


def _match_option(value: str, options):
    """Точный текст опции select по нормализованному равенству/вхождению, иначе None."""
    vn = _norm(value)
    if not vn:
        return None
    for opt in options:
        on = _norm(opt)
        if on and (on == vn or vn in on or on in vn):
            return opt
    return None


def _map_checkbox_groups(checkbox_fields, value_set, consent_names, res) -> None:
    """Группируем чекбоксы по name. Не-consent группу заполняем опцией, чьё label
    совпало с disclosed-значением. Consent или без-совпадения required → unmatched
    (ОДИН раз на группу). Стоячее согласие (по имени поля или, для single-option групп,
    по тексту question-level group_label) уходит в auto_consents вместо unmatched."""
    groups: dict[str, list] = {}
    order: list[str] = []
    for f in checkbox_fields:
        if f.name not in groups:
            groups[f.name] = []
            order.append(f.name)
        groups[f.name].append(f)
    for name in order:
        opts = groups[name]
        # is_standing вычисляется ДО is_consent: для company-custom вопросов с общим
        # текстом чекбокса ("Confirm"/"Acknowledge") единственный стабильный сигнал —
        # question-level group_label, а не текст самой опции (§3 — looks_like_consent
        # по label может не сработать, но матч по group_label всё равно должен и
        # определить это как consent-группу, и сразу пометить её стоячей).
        is_standing = name in _STANDING_CONSENT_NAMES
        if not is_standing and len(opts) == 1:
            is_standing = looks_like_standing_label_consent(opts[0].group_label)
        is_consent = (
            is_standing or name in consent_names
            or any(looks_like_consent(o.label) for o in opts)
        )
        if is_consent:
            if is_standing:
                res.auto_consents.append(name)
            elif any(o.required for o in opts):
                res.unmatched_required.append(name)
            continue
        chosen = next(
            (o for o in opts if _norm(o.label or "") and _norm(o.label) in value_set),
            None)
        required = any(o.required for o in opts)
        if chosen is None and required:
            # Demographic/EEO-группа (gender/race/veteran/disability) с явной
            # decline-опцией на форме — политика владельца уже задокументирована
            # (§3, "Leave blank / decline where supported"); честный disclosed-ответ
            # выше всегда в приоритете, decline — только когда матча не нашлось.
            chosen = next((o for o in opts if looks_like_decline_option(o.label)), None)
        if chosen is None and required and len(opts) > 1 \
                and _looks_like_location_question(opts[0].group_label):
            # "Which is your preferred location for this role?" — company-specific
            # список офисов/городов (владелец, 2026-07-24): Remote, если есть среди
            # опций, иначе первая по порядку формы. Раскрытое значение (проверка выше)
            # остаётся в приоритете над этим дефолтом.
            chosen = next((o for o in opts if "remote" in (o.label or "").lower()), None) \
                or opts[0]
        if chosen is None and required and len(opts) > 1 \
                and _looks_like_other_fallback_eligible_question(opts[0].group_label) \
                and not _looks_like_demographic_group(opts):
            # Общий catch-all "Other" (владелец, 2026-07-24) — ТОЛЬКО для известных
            # безопасных форм вопроса (allowlist по group_label, как и preferred-location
            # выше): изначальная permissive-версия рисковала выбрать "Other" на
            # blocked-факте (work authorization/sponsorship/German level с опцией
            # "Other" — code-review finding, 2026-07-24). "Other" ничего не утверждает
            # сверх "не одно из перечисленного" — но только когда вопрос заведомо про
            # location/source, а не про факт, который §3 обязан оставлять честно
            # неизвестным. Demographic-гейт — defense-in-depth поверх allowlist.
            chosen = next(
                (o for o in opts if _norm(o.label or "") == "other"), None)
        if chosen is not None:
            res.fields[name] = chosen.label
            res.matched.append((chosen.label or name).split(" (")[0].strip())
        elif required:
            res.unmatched_required.append(name)


def map_fields(answers, consents, schema: FormSchema, ats_family=None) -> MappingResult:
    """Сопоставить disclosed answers с полями формы. consents в значения не идут.

    Чекбоксы обрабатываются ПО ГРУППЕ (один name = группа опций): не-consent группу
    заполняем опцией, чьё label совпало с disclosed-значением (§3-безопасно)."""
    idx = _answers_index(answers)
    value_set = {_norm(a.value) for a in answers if getattr(a, "value", None)}
    consent_names = set(schema.consent_checkboxes or [])
    res = MappingResult()
    if schema.file_inputs:
        res.resume_field = schema.file_inputs[0]

    _map_checkbox_groups(
        [f for f in schema.fields if f.field_type == "checkbox"],
        value_set, consent_names, res)

    for field in schema.fields:
        if field.field_type in ("file", "checkbox"):
            continue
        value = _candidate_value(field, idx)
        if value is None:
            if field.required and not _AUTO_FIELD_RE.match(field.name):
                res.unmatched_required.append(field.name)
            continue
        if field.field_type == "select":
            opt = _match_option(value, field.options)
            if opt is None:
                if field.required:
                    res.unmatched_required.append(field.name)
                continue
            value = opt
        res.fields[field.name] = value
        if field.label:
            res.matched.append(field.label.split(" (")[0].strip())
        else:
            res.matched.append(field.name)
    return res
