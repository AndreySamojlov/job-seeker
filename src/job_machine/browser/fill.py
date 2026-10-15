"""Заполнение формы и ОСТАНОВКА до отправки (контур безопасности устава §3).

Здесь нет нажатия кнопки отправки — кнопка submit не трогается. Реальная отправка —
план 6 (Approval+Submit), только при валидном one-time токене на точный payload_hash.

Робастность (фиксы среза 2): селекторы строятся через атрибут [name=...]/[id=...] с
экранированием — реальные ATS-имена содержат скобки (job_application[answers][0]), которые
ломают id-селектор #{name}. select_option пробует точный текст/значение, затем нормализованную
опцию и НЕ падает: несопоставленное поле уходит в FillResult.unmatched.
"""

import asyncio
import re
import time
from urllib.parse import urlsplit

from job_machine.browser.schema import FillResult, SubmitResult


def _css_attr(attr: str, value: str) -> str:
    """[attr="value"] с экранированием кавычек/бэкслешей; скобки внутри кавычек безопасны."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'[{attr}="{escaped}"]'


def _css_attr_prefix(attr: str, value: str) -> str:
    """[attr^="value"] с экранированием — префиксный селектор для react-select
    option-id вида react-select-{name}-option-N."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'[{attr}^="{escaped}"]'


def _locator(page, name: str):
    """Локатор по name, затем по id — оба атрибутными селекторами (скобко-безопасно)."""
    return page.locator(f"{_css_attr('name', name)}, {_css_attr('id', name)}").first


def _norm(text: str) -> str:
    s = re.sub(r"[^a-z0-9 ]+", " ", (text or "").lower())
    return re.sub(r"\s+", " ", s).strip()


async def _label_for_el(page, el) -> str | None:
    """Текст <label for=id> элемента, иначе aria-label/placeholder."""
    el_id = await el.get_attribute("id")
    if el_id:
        esc = el_id.replace("\\", "\\\\").replace('"', '\\"')
        lbl = page.locator(f'label[for="{esc}"]')
        if await lbl.count() > 0:
            return (await lbl.first.inner_text()).strip()
    return await el.get_attribute("aria-label") or await el.get_attribute("placeholder")


def _checkbox_group(page, name):
    """Локатор именно input[type=checkbox] группы по name/id (минуя оборачивающий
    <fieldset id=...>, который в Greenhouse несёт тот же id, что и name инпутов)."""
    return page.locator(
        f'input[type="checkbox"]{_css_attr("name", name)}, '
        f'input[type="checkbox"]{_css_attr("id", name)}')


async def _check_option_in_group(page, name, value) -> bool:
    """Отметить в группе чекбокс, чей label нормализованно равен value (опции).
    Возвращает True только при точном совпадении label — truthy-fallback удалён (§3)."""
    group = _checkbox_group(page, name)
    n = await group.count()
    vn = _norm(value)
    for i in range(n):
        el = group.nth(i)
        if vn and _norm(await _label_for_el(page, el) or "") == vn:
            await el.check()
            return True
    return False


def _normalized_match(candidate: str, value: str) -> bool:
    """Нормализованное совпадение (равенство или подстрока в любую сторону) —
    общий предикат для select-опций и react-select-опций.

    Оба, и candidate, и value, должны быть непустыми после нормализации: иначе
    пустая строка — тривиальная подстрока любой другой строки (`"" in x`), и
    placeholder-опция вида "-- Select --" (нормализуется в "select", но пустая
    опция без текста нормализуется в "") ложно "совпала" бы с чем угодно."""
    vn = _norm(value)
    cn = _norm(candidate)
    return bool(vn) and bool(cn) and (cn == vn or vn in cn or cn in vn)


async def _select_robust(loc, value: str) -> bool:
    """Выбрать опцию по точному тексту/значению, иначе по нормализованному тексту.

    Опции читаем ЗАРАНЕЕ и выбираем только при заведомом совпадении — без управления
    потоком через исключения (иначе select_option на несовпадении ждёт до таймаута).
    True если опция выбрана, False если совпадения нет.
    """
    option_texts = await loc.locator("option").all_inner_texts()
    option_values = await loc.locator("option").evaluate_all("els => els.map(e => e.value)")
    if value in option_texts:
        await loc.select_option(label=value)
        return True
    if value in option_values:
        await loc.select_option(value=value)
        return True
    for opt in option_texts:
        if _normalized_match(opt, value):
            await loc.select_option(label=opt)
            return True
    return False


_COMBOBOX_STATIC_TIMEOUT_MS = 1500   # статичный список открывается сразу
_COMBOBOX_SEARCH_TIMEOUT_MS = 8000   # debounce + сетевой geocoding round-trip
_COMBOBOX_TYPE_DELAY_MS = 30         # посимвольная задержка ввода


def _option_locator(page, name: str):
    """Локатор всех react-select-опций поля name (react-select-{name}-option-N)."""
    return page.locator(_css_attr_prefix("id", f"react-select-{name}-option-"))


async def _match_and_click_option(page, name: str, value: str) -> bool:
    """Кликнуть опцию react-select, чей текст нормализованно совпадает с value.

    Клик обёрнут в try/except (review-finding): опция может быть attached, но не
    actionable (анимация/оверлей/вне вьюпорта) — Playwright тогда ждёт actionability
    до собственного дефолтного таймаута (30с) и может кинуть исключение; без guard'а
    это прервало бы обработку ВСЕХ оставшихся полей формы, а не только текущего."""
    options = _option_locator(page, name)
    n = await options.count()
    for i in range(n):
        opt = options.nth(i)
        text = (await opt.inner_text()).strip()
        if _normalized_match(text, value):
            try:
                await opt.click()
                return True
            except Exception:  # noqa: BLE001 — не сорвать весь fill_form из-за одной опции
                return False
    return False


async def _wait_for_options(page, name: str, timeout_ms: int) -> bool:
    """Дождаться появления хотя бы одной react-select-опции; True если появились,
    False по таймауту (значит опций нет — не фатально, вызывающий код решает,
    что делать дальше)."""
    try:
        await _option_locator(page, name).first.wait_for(state="attached", timeout=timeout_ms)
        return True
    except Exception:  # noqa: BLE001 — таймаут ожидаем, не ошибка
        return False


async def _fill_react_select_combobox(page, loc, name: str, value: str) -> bool:
    """Заполнить react-select-комбобокс (owner-approval 2026-07-23, узкое
    исключение fill-path denylist — см. docs/superpowers/specs/
    2026-07-23-geo-autocomplete-fill-design.md).

    Клик открывает меню. Если опции готовы сразу — статичный список: матчим и
    кликаем. Если пусто — debounced geo-autocomplete (напр. Addepar Location
    City): печатаем value посимвольно (press_sequentially, НЕ .fill() — иначе
    debounced поиск не триггерится) и ждём дольше. Разрешены ТОЛЬКО .click() и
    press_sequentially() — никаких Enter/Tab/submit (см. тест-инвариант).

    Security-fix (review 2026-07-24): Playwright's press_sequentially/type
    treats literal \\n/\\r in the string as the Enter key — a real keydown/keyup,
    not just inserted text. Поле сидит в реальной <form> рядом с submit-кнопкой,
    поэтому значение с переводом строки могло бы неявно отправить форму — прямое
    нарушение инварианта "fill-path никогда не сабмитит". Печатаем только
    санитизированную копию; матчинг опций остаётся по исходному value (текст
    опции сравниваем с настоящим намерением, не с урезанной строкой ввода).

    Review-fix (2026-07-24): открывающий клик тоже обёрнут в try/except — тот же
    риск неактуируемого элемента (напр. под cookie-баннером — pre-submit fill-path
    не вызывает _dismiss_cookie_banner, это делает только submit_form), что и у
    opt.click() в _match_and_click_option; без guard'а необработанное исключение
    сорвало бы обработку всех остальных полей формы."""
    try:
        await loc.click()
    except Exception:  # noqa: BLE001 — не срывать обработку остальных полей формы
        return False
    if await _wait_for_options(page, name, _COMBOBOX_STATIC_TIMEOUT_MS):
        return await _match_and_click_option(page, name, value)
    safe_value = value.replace("\r", " ").replace("\n", " ")
    await loc.press_sequentially(safe_value, delay=_COMBOBOX_TYPE_DELAY_MS)
    if await _wait_for_options(page, name, _COMBOBOX_SEARCH_TIMEOUT_MS):
        return await _match_and_click_option(page, name, value)
    return False


async def fill_form(page, fields, resume_path=None, screenshot_path=None,
                    consent_checks: list | None = None):
    """Заполнить text/select/checkbox-поля и приложить резюме; отправку не делаем."""
    filled = []
    unmatched = []
    for name, value in fields.items():
        # Чекбокс-группу детектируем ПЕРВОЙ — по самим input[type=checkbox], чтобы не
        # зацепить оборачивающий <fieldset id=name> (у него нет type → иначе попытка
        # loc.fill() на fieldset → 500).
        if await _checkbox_group(page, name).count() > 0:
            if await _check_option_in_group(page, name, value):
                filled.append(name)
            else:
                unmatched.append(name)
            continue
        loc = _locator(page, name)
        if await loc.count() == 0:
            unmatched.append(name)
            continue
        if await loc.get_attribute("role") == "combobox":
            if await _fill_react_select_combobox(page, loc, name, value):
                filled.append(name)
            else:
                unmatched.append(name)
            continue
        tag = await loc.evaluate("e => e.tagName.toLowerCase()")
        ftype = (await loc.get_attribute("type")) or ""
        if tag == "select":
            if await _select_robust(loc, value):
                filled.append(name)
            else:
                unmatched.append(name)
        elif ftype == "checkbox":
            if await _check_option_in_group(page, name, value):
                filled.append(name)
            else:
                unmatched.append(name)
        else:
            await loc.fill(value)
            filled.append(name)

    for name in (consent_checks or []):
        group = _checkbox_group(page, name)
        if await group.count() > 0:
            await group.first.check()
            filled.append(name)
        else:
            loc = _locator(page, name)
            if await loc.count() > 0:
                await loc.first.check()
                filled.append(name)
            else:
                unmatched.append(name)

    resume_attached = False
    if resume_path:
        file_loc = page.locator("input[type='file']").first
        if await file_loc.count() > 0:
            await file_loc.set_input_files(resume_path)
            resume_attached = True

    if screenshot_path:
        await page.screenshot(path=screenshot_path)

    return FillResult(
        filled=filled,
        resume_attached=resume_attached,
        stopped_before_submit=True,
        screenshot_path=screenshot_path,
        unmatched=unmatched,
    )


# Стабильные глобальные ID OneTrust (самый частый вендор, живой инцидент 17.07.2026
# ниже) — можно матчить по всей странице без риска задеть контрол самой формы: это
# конкретные ID виджета, а не текстовое совпадение.
_ONETRUST_REJECT = "#onetrust-reject-all-handler"
_ONETRUST_ACCEPT = "#onetrust-accept-btn-handler"

# Прочие вендоры — по тексту, но ТОЛЬКО внутри контейнера, похожего на cookie-баннер
# (review-finding: нескоуп­ленный `button:has-text('Decline')` рисковал бы кликнуть
# настоящий контрол формы — напр. вопрос анкеты "Decline to answer").
_COOKIE_BANNER_CONTAINERS = (
    "#onetrust-banner-sdk",
    "#onetrust-pc-sdk",
    "[id*='cookie-consent' i]",
    "[id*='cookie-banner' i]",
    "[id*='cookiebanner' i]",
    "[class*='cookie-consent' i]",
    "[class*='cookie-banner' i]",
    "[class*='cookiebanner' i]",
    "[aria-label*='cookie' i]",
)
_REJECT_TEXTS = ("Reject All", "Reject all", "Decline", "Only necessary", "Only essential")
_ACCEPT_TEXTS = ("Accept All", "Accept all", "I agree", "Got it")


async def _try_click(page, selector: str) -> bool:
    loc = page.locator(selector).first
    if await loc.count() == 0:
        return False
    try:
        if not await loc.is_visible():
            return False
        await loc.click(timeout=2_000)
        return True
    except Exception:  # noqa: BLE001 — не тот элемент/уже исчез, не фатально
        return False


async def _dismiss_cookie_banner(page) -> None:
    """Отклонить/закрыть cookie-consent баннер (OneTrust и подобные), если он
    перекрывает форму — privacy-preserving по умолчанию: сначала reject/decline,
    accept только если reject-опции нет (CLAUDE.md §3 — decline non-essential).

    Живой инцидент 17.07.2026 (Kaseya, application_id 2687c55f-...): OneTrust
    dark-filter оверлей (position:fixed, z-index) перехватывал клик по кнопке
    submit — Locator.click упирался в 30с таймаут ("subtree intercepts pointer
    events"), хотя сама кнопка была найдена верно. Вызывается ДО fill_form (не
    только перед submit) — тот же оверлей перехватывает и клики по чекбоксам
    согласия внутри формы (review-finding: consent-чекбоксы часто соседствуют с
    cookie-баннером внизу формы).

    Best-effort: если баннера нет или клик не удался — молча продолжаем.
    """
    if await _try_click(page, _ONETRUST_REJECT):
        return
    if await _try_click(page, _ONETRUST_ACCEPT):
        return
    for container in _COOKIE_BANNER_CONTAINERS:
        for text in _REJECT_TEXTS + _ACCEPT_TEXTS:
            if await _try_click(page, f"{container} button:has-text('{text}')"):
                return


_NAVIGATION_ERROR_MARKERS = (
    "Execution context was destroyed",
    "Target closed",
    "Target page, context or browser has been closed",
)


async def _invalid_fields_signal(scope_handle) -> str | None:
    """После клика форма могла остаться на месте — проверяем два независимых
    сигнала провала и возвращаем, какой именно сработал (None — оба чисты).

    (1) "native_invalid": сам браузер блокирует нативный submit, если
    required-поле (в т.ч. чужой кастомный <select required>, не сопоставленный
    ни с одним claim'ом — work authorization/demographic и т.п., §3 намеренно
    не автозаполняются) пусто, и подсвечивает его :invalid — это ровно то
    состояние, что видно на скриншотах живого инцидента 23.07.2026 («This
    field is required», кнопка Submit всё ещё на месте). Надёжный сигнал: не
    завязан на текст/локаль конкретного ATS.

    (2) "aria_invalid": видимый [aria-invalid="true"] элемент — custom-виджеты
    без нативного required (react-select и подобные — подтверждено 23.07.2026
    на живом Greenhouse-постинге job-boards.eu.greenhouse.io/jetbrains/jobs/
    4695264101: combobox там валидируется целиком через aria-required/
    aria-invalid, не через HTML5 constraint API, так что :invalid на нём
    никогда не сработает) сами выставляют этот атрибут при неудачной попытке
    отправки. Именно эта форма провала видна на сэмпле исторических
    submit_confirm.png (заявка 02.07.2026) — не теоретический случай. Известная
    слепая зона: `offsetParent === null` также истинно для `position: fixed`
    элементов (напр. sticky-баннер с ошибкой) — такой виджет эта проверка
    пропустит, хотя он реально виден пользователю.

    Скоуп — сама отправленная <form> (handle снят ДО клика), не весь document:
    посторонний required-и-пустой виджет в другом месте страницы (чат-виджет,
    форма подписки на новости) не должен ложно провалить настоящий успех.

    Что именно считается провалившим `:invalid` — в _BLOCKING_INVALID_JS: то же
    правило читает и _PAGE_SNAPSHOT_JS, и разъезжаться им нельзя.

    Живой OKX (08.08.2026) — почему правило вообще уточнялось: у группы «What
    language(s) are you fluent in?» `required` стоял на всех 31 чекбоксе и не
    снимался при выборе, так что сплошной подсчёт `:invalid` объявлял провал на
    КАЖДОЙ попытке и делал errors_absent — а с ним и любое подтверждение —
    недостижимым. Нативная валидация ту форму не блокировала: кнопка submit
    делает preventDefault на click и отправляет собственный XHR.
    """
    try:
        return await scope_handle.evaluate(
            "scope => {" + _BLOCKING_INVALID_JS +
            "  if (blockingInvalid(scope).length) return 'native_invalid';"
            "  const ariaInvalid = Array.from(scope.querySelectorAll('[aria-invalid=\"true\"]'))"
            "    .some(el => el.offsetParent !== null);"
            "  return ariaInvalid ? 'aria_invalid' : null;"
            "}")
    except Exception as exc:  # noqa: BLE001
        # Реальная навигация — старый handle просрочен, это не провал.
        # Любая ДРУГАЯ ошибка — неопределённость, не подтверждённый успех:
        # пробрасываем наверх (submit-сервис заведёт broken_flow), а не тихо
        # трактуем как success — ровно такое "по умолчанию успех" и было
        # корнем живого инцидента 23.07.2026.
        if any(marker in str(exc) for marker in _NAVIGATION_ERROR_MARKERS):
            return None
        raise


# Токены страницы подтверждения — сверяются ТОЛЬКО с path (схема, хост и query
# отброшены) и ТОЛЬКО по границам токенов. Подстрочный матч по всему URL давал
# ложные срабатывания на реальных адресах (review 05.08.2026): "success" внутри
# career5.successfactors.eu (один из крупнейших ATS мира), "applied" внутри
# appliedmaterials.wd1.myworkdayjobs.com/.../apply/error, "confirmation" внутри
# company.com/login?next=%2Fapplication%2Fconfirmation (типовое падение сессии
# ровно в момент отправки).
_CONFIRMATION_PATH_TOKENS = frozenset({
    "confirmation", "confirmed", "thanks", "thankyou",
    "success", "submitted", "applied", "received",
})

# Фразы завершённой подачи. Намеренно длинные и однозначные: короткое "thank you"
# встречается и на самой форме ("thank you for your interest"), а ложное
# подтверждение — это ровно инцидент 23.07.2026. Сравниваются с _norm-текстом
# страницы, поэтому пишутся уже нормализованно (без пунктуации).
_THANK_YOU_TEXT_MARKERS = (
    "thank you for applying",
    "thanks for applying",
    "thank you for your application",
    "your application has been submitted",
    "your application was submitted",
    "your application has been received",
    "we have received your application",
    "your submission has been received",
    "successfully submitted",
)

# Прямые признаки провала: подстрочный матч фразы благодарности их не видит
# ("your application was NOT submitted" не содержит "was submitted", но соседняя
# фраза благодарности на той же странице — вполне возможна).
_SUBMISSION_FAILURE_MARKERS = (
    "not submitted",
    "not been submitted",
    "not be submitted",
    "was not received",
    "has not been received",
    "unable to submit",
    "could not be submitted",
    "could not process",
    "cannot be submitted",
    "cannot process",
    "failed to submit",
    "there was a problem",
    "something went wrong",
    "please correct",
    "please try again",
    "an error occurred",
    "errors below",
    # Дубль: «Thank you for applying» в шапке при том, что текущая попытка
    # ничего не создала (review 05.08.2026).
    "already applied",
    "already submitted an application",
    "duplicate application",
)


# Инлайн email-верификация после клика Submit (живой инцидент 08-09.08.2026,
# GitLab/Greenhouse): ни :invalid, ни aria-invalid, ни фраза благодарности не
# срабатывают — форма и кнопка Submit остаются на месте, просто внизу появляется
# поле кода. Без этого различителя исход неотличимо тонет в generic
# "no_confirmation" (submit/service.py::_submit_claim). Классификация ЧИСТО
# статистическая (CLAUDE.md §6, порог 5/10 не пройден на 1/10 живых попыток) —
# retain-логику сессии это не меняет.
_EMAIL_VERIFICATION_MARKERS = (
    "verification code was sent",
    "resubmit your application",
)


def _looks_like_email_verification(text: str) -> bool:
    norm = _page_norm(text or "")
    return any(marker in norm for marker in _EMAIL_VERIFICATION_MARKERS)


def _path_confirms(url: str) -> bool:
    """Есть ли в path отдельный токен страницы подтверждения. Токен, а не
    подстрока: "success" — да, "successfactors" — нет."""
    tokens = _path_tokens(url)
    if any(t in _CONFIRMATION_PATH_TOKENS for t in tokens):
        return True
    return any(a == "thank" and b == "you" for a, b in zip(tokens, tokens[1:]))


def _affirmative_confirmation(text: str) -> bool:
    """Утверждает ли текст, что подача СОСТОЯЛАСЬ: есть фраза завершённой подачи
    и нет ни одного прямого признака провала.

    Списка условных связок здесь больше нет (review 05.08.2026): бойлерплейт
    «what happens next» отсекается структурно — фраза засчитывается только в
    заголовке или статус-регионе, а обещание живёт в абзаце. Закрытый список
    обходился оборотами "as soon as"/"in the event that" и создавал впечатление
    защиты, которой нет."""
    if not text or any(m in text for m in _SUBMISSION_FAILURE_MARKERS):
        return False
    return any(marker in text for marker in _THANK_YOU_TEXT_MARKERS)


# Подпись отправляемой формы снимается ДО клика с того же handle, который и так
# нужен для _invalid_fields_signal, и после клика ищется на живом документе.
# Это точное сопоставление вместо угадывания «похоже на анкету» (review
# 05.08.2026): эвристика по числу полей и типу кнопки ошибалась в обе стороны
# сразу — не узнавала ре-рендер анкеты из двух полей и React-кнопку
# type="button", зато принимала за анкету шапочный поиск вакансий. Сервер при
# ре-рендере обязан сохранить имена полей (иначе не восстановит введённые
# значения), а поиск вакансий и подписка на рассылку по именам не совпадут
# никогда.
_FORM_SIGNATURE_JS = """
scope => {
  if (!scope || scope.nodeType === 9) return null;
  const names = Array.from(scope.querySelectorAll('[name]'))
    .map(el => el.getAttribute('name')).filter(Boolean);
  return {id: scope.id || '', action: scope.getAttribute('action') || '',
          names: Array.from(new Set(names))};
}
"""

# Один снимок страницы на всё доказательство. Четыре отдельных evaluate читали
# состояние в четыре разных момента, и на SPA доказательство складывалось из
# несогласованного снимка (review 05.08.2026).
#
# Две разные проверки видимости — намеренно, они смотрят в противоположные
# стороны безопасности. `present` (щедрая) — для форм и ошибок: если сомневаемся,
# считаем, что элемент на экране, то есть доказательства меньше. `shown`
# (строгая) — для якорей подтверждения: скрытая благодарность засчитываться не
# должна. Текст берём из innerText (он и сам не видит скрытого) — fallback на
# textContent давал ровно обратную асимметрию: скрытый текст не давал маркеров
# провала, но давал маркеры успеха.
#
# `shown` проверяет и геометрию, а не только стили (review 05.08.2026):
# checkVisibility закрывает display/visibility/opacity/content-visibility, но
# визуально скрытый текст для скринридеров делают геометрией — обрезкой в
# нулевой прямоугольник, выносом за левый край, нулевым кеглем, отрицательным
# text-indent, clip-path. Бьёт это именно по role=status: визуально скрытая
# live-регион-озвучка штатна, и старую фразу в ней часто не чистят после смены
# состояния. Меряем прямоугольник и самого элемента, и его текста (Range) —
# text-indent сдвигает только текст, коробка остаётся на месте. За пределами
# документа = правее/ниже нуля с учётом скролла, поэтому текст ниже сгиба и
# прокрученный вверх засчитываются нормально.
# Единственное определение «что считается провалившим форму :invalid». Его
# применяют ДВА независимых читателя — _invalid_fields_signal (по хендлу формы,
# снятому до клика) и _PAGE_SNAPSHOT_JS (по живому документу после). Разъехавшись,
# они дают ровно тот отказ, ради которого правило и уточнялось: одна проверка
# отпускает подачу, вторая по-прежнему объявляет «на странице ошибки», и
# доказательство не собирается (живой OKX, третья попытка 17:17 UTC 08.08.2026).
#
# Исключены две категории, ничего не говорящие об исходе:
#   * чекбокс отвеченной группы — HTML применяет `required` к каждому варианту
#     поштучно, но вопрос отвечен, как только выбран один; Greenhouse на это и
#     рассчитывает и `required` с соседей не снимает (у OKX группа «What
#     language(s) are you fluent in?» держала :invalid на 30 из 31 навсегда);
#   * контейнеры <fieldset>/<form> — они :invalid производно, из-за вложенного
#     контрола, который и так попадёт в список, если провален по-настоящему.
# Неотвеченная группа и одиночный обязательный чекбокс согласия ловятся как прежде.
_BLOCKING_INVALID_JS = """
  const blockingInvalid = scope => {
    const answered = new Set();
    scope.querySelectorAll('input[type="checkbox"][name]').forEach(
      cb => { if (cb.checked) answered.add(cb.name); });
    return Array.from(scope.querySelectorAll(':invalid')).filter(el => {
      if (el.tagName === 'FIELDSET' || el.tagName === 'FORM') return false;
      if (el.type === 'checkbox' && el.name && answered.has(el.name)) return false;
      return true;
    });
  };
"""

_PAGE_SNAPSHOT_JS = """
sig => {
""" + _BLOCKING_INVALID_JS + """
  const present = el => el.offsetParent !== null ||
    (el.getClientRects && el.getClientRects().length > 0);
  const sane = r => r.width > 2 && r.height > 2 &&
    r.right + window.scrollX > 0 && r.bottom + window.scrollY > 0;
  const shown = el => {
    if (el.closest('[aria-hidden="true"]')) return false;
    if (typeof el.checkVisibility === 'function' &&
        !el.checkVisibility({visibilityProperty: true, opacityProperty: true,
                             contentVisibilityAuto: true})) return false;
    const style = getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden') return false;
    if (style.clipPath !== 'none' || style.clip !== 'auto') return false;
    if (!sane(el.getBoundingClientRect())) return false;
    const range = document.createRange();
    range.selectNodeContents(el);
    return sane(range.getBoundingClientRect());
  };
  const trivial = v => !v || v === '#' || v === '/';
  const sameForm = f => {
    if (!sig) return false;
    if (!trivial(sig.id) && f.id === sig.id) return true;
    if (!trivial(sig.action) && f.getAttribute('action') === sig.action) return true;
    const names = new Set(Array.from(f.querySelectorAll('[name]'))
      .map(el => el.getAttribute('name')).filter(Boolean));
    const hit = sig.names.filter(n => names.has(n)).length;
    const need = sig.names.length <= 1
      ? sig.names.length : Math.max(2, Math.ceil(sig.names.length / 2));
    return need > 0 && hit >= need;
  };
  // Неопознанная форма, которая по размеру всё-таки похожа на анкету: сервер мог
  // сменить идентичность целиком (другой id/action, имена с префиксом), и тогда
  // "я не нашёл свою форму" неотличимо от "формы нет".
  const bulky = f => {
    if (!f.querySelector("button:not([type='button']):not([type='reset'])," +
                         " input[type='submit'], button[type='button']")) return false;
    if (f.querySelector("input[type='file']")) return true;
    return f.querySelectorAll(
      "input:not([type='submit']):not([type='button']):not([type='reset'])" +
      ":not([type='hidden']), select, textarea, [role='combobox']," +
      " [contenteditable='true']").length >= 5;
  };
  const visibleForms = Array.from(document.querySelectorAll('form')).filter(present);
  const forms = visibleForms.filter(sameForm);
  const ariaBad = Array.from(document.querySelectorAll('[aria-invalid="true"]'))
    .some(present);
  const invalid = forms.some(f => blockingInvalid(f).some(present));
  return {
    text: document.body ? document.body.innerText : '',
    anchors: Array.from(document.querySelectorAll(
      "h1, h2, h3, [role='status'], [role='alert']")).filter(shown)
      .map(el => el.innerText || ''),
    form_present: forms.length > 0,
    unidentified_form_present: visibleForms.filter(f => !sameForm(f)).some(bulky),
    errors_present: ariaBad || invalid,
  };
}
"""


def _denormalize_contractions(text: str) -> str:
    """Вернуть "not" в стянутые формы: _norm съедает апостроф, и "couldn't
    process" превращается в "couldn t process", мимо маркера "could not
    process" (так и прошёл ложноположительный случай в review 05.08.2026)."""
    text = re.sub(r"\bcan t\b", "cannot", text)
    return re.sub(r"([a-z]+)n t\b", r"\1 not", text)


def _page_norm(raw: str) -> str:
    """Нормализованный текст для сверки с маркерами."""
    return _denormalize_contractions(_norm(raw or ""))


def _path_tokens(url: str) -> list[str]:
    """Токены пути URL: схема, хост и query отброшены, разделители — не буквы."""
    try:
        path = urlsplit(url or "").path.lower()
    except ValueError:
        return []
    return [t for t in re.split(r"[^a-z0-9]+", path) if t]


async def _form_signature(form_handle):
    """Подпись отправляемой формы (снимается ДО клика). None — подписи нет:
    formless-страница (handle указывает на document) ЛИБО форма без id, без
    action и без имён у контролов. Пустая подпись не совпадает ни с чем, а
    значит объявила бы исчезнувшей форму, стоящую на экране (review 05.08.2026;
    React-идиом — onSubmit плюс управляемые инпуты только с id, fill его штатно
    поддерживает). Тогда отсутствие формы честно остаётся недоказанным.

    Дополнять подпись идентификаторами контролов нельзя: React-генераторы id
    выдают новый id на каждый рендер, подпись перестанет совпадать сама с собой
    и даст тот же ложный успех.
    """
    try:
        signature = await form_handle.evaluate(_FORM_SIGNATURE_JS)
    except Exception:  # noqa: BLE001 — не сняли => доказывать нечем
        return None
    if not isinstance(signature, dict):
        return None
    if not (signature.get("id") or signature.get("action") or signature.get("names")):
        return None
    return signature


async def _page_snapshot(page, signature):
    """Согласованный снимок страницы после клика: текст, якоря, наличие той же
    формы и наличие ошибок — одним вызовом. None при любой ошибке чтения."""
    try:
        snapshot = await page.evaluate(_PAGE_SNAPSHOT_JS, signature)
    except Exception:  # noqa: BLE001 — не прочитали => не доказали
        return None
    return snapshot if isinstance(snapshot, dict) else None


def _confirmation_signal(snapshot, url_before: str, url_after: str) -> str | None:
    """Чем подтверждена подача. None — подтверждения нет.

    [SAFETY] Требуется утвердительная фраза завершённой подачи В ВИДИМОМ
    ЗАГОЛОВКЕ ИЛИ СТАТУС-РЕГИОНЕ страницы ПОСЛЕ клика и ни одного признака
    провала во всём её видимом тексте. URL сам по себе подтверждением не
    является и лишь уточняет метку.

    Почему так (review 05.08.2026): текст, взятый из всего innerText без
    привязки к месту, ловится карьерным лендингом с блоком «what happens next:
    as soon as we have received your application...». Настоящее подтверждение
    ставит фразу в заголовок, обещание — в абзац.
    """
    if snapshot is None:
        return None
    page_text = _page_norm(snapshot.get("text") or "")
    if not page_text or any(m in page_text for m in _SUBMISSION_FAILURE_MARKERS):
        return None
    if not any(_affirmative_confirmation(_page_norm(anchor))
               for anchor in snapshot.get("anchors") or []):
        return None
    if url_after and url_after != url_before and _path_confirms(url_after):
        return "confirmation_url"
    return "thank_you_text"


# Сколько ждать исхода клика и как часто переспрашивать страницу. 45с выбраны с
# запасом под медленный ATS и заведомо меньше и лизы попытки (600с), и таймаута
# HTTP-клиента MCP (300с) — ожидание не может пережить вызывающего.
_SUBMIT_OUTCOME_BUDGET_S = 45.0
_SUBMIT_OUTCOME_POLL_S = 0.5
# Сколько терпеть нечитаемую страницу. Снимок не снимается, пока идёт навигация —
# это доли секунды. Если не читается дольше, исход не станет наблюдаемым вообще,
# и выжидать весь бюджет значит держать вызывающего впустую.
_SUBMIT_UNREADABLE_GRACE_S = 5.0


async def _wait_for_submit_outcome(page, signature, url_before: str,
                                   budget_s: float = _SUBMIT_OUTCOME_BUDGET_S,
                                   poll_s: float = _SUBMIT_OUTCOME_POLL_S,
                                   unreadable_grace_s: float = _SUBMIT_UNREADABLE_GRACE_S):
    """Дождаться, пока у клика появится исход, и вернуть снимок страницы.

    Живой инцидент 08.08.2026 (OKX, job-boards.greenhouse.io/okx/jobs/7739163003):
    вердикт снимался сразу после `wait_for_load_state("networkidle")`, а тот
    возвращался мгновенно — в момент вызова на странице ещё ничего не летело.
    Наблюдение живой страницы раз в 1.5с показало, что кнопка оставалась
    обычной и активной ~9 секунд после клика и лишь потом ушла в спиннер:
    сайт стартовал свой XHR сильно позже. Воркер к тому времени уже записал
    исход `unknown` и через секунду уничтожил страницу, оборвав отправку на
    первой секунде. Две попытки подряд погибли так.

    Терминальным считается первое из: отправленной формы на странице больше
    нет, появились видимые ошибки, сменился URL. Ни одного за бюджет — честно
    возвращаем последний снимок: недоказанная подача останется недоказанной,
    порог доказательства это ожидание не трогает.
    """
    started = time.monotonic()
    deadline = started + budget_s
    unreadable_since = None
    snapshot = None
    while True:
        snapshot = await _page_snapshot(page, signature)
        if snapshot is None:
            # Нечитаемая страница: терпим только короткую слепоту навигации.
            unreadable_since = unreadable_since or time.monotonic()
            if time.monotonic() - unreadable_since >= unreadable_grace_s:
                return None
        else:
            unreadable_since = None
            if (not snapshot["form_present"] or snapshot["errors_present"]
                    or page.url != url_before):
                return snapshot
        if time.monotonic() >= deadline:
            return snapshot
        await asyncio.sleep(poll_s)


async def submit_form(page, fields, resume_path=None, screenshot_path=None,
                      consent_checks: list | None = None) -> SubmitResult:
    """Заполнить форму и нажать кнопку submit; вернуть URL подтверждения.

    Гарды безопасности (NoSubmitWithoutApproval и др.) проверяет submit-воркер
    ДО вызова этого метода — браузер-воркер является чистым DOM-примитивом.

    Живой инцидент 23.07.2026: submit считался успешным по факту клика, без
    проверки результата — 145+ заявок помечены submitted, при этом скриншот
    подтверждения на деле показывал форму с ошибками валидации ("This field is
    required"), а сами компании ни разу не прислали подтверждающее письмо. Три
    независимых сигнала провала ниже закрывают эту часть инцидента: (1) поле,
    которое сам fill_form не смог заполнить (locator не найден/select без
    совпадающей опции) — вообще не жмём submit, раз заведомо неполные данные;
    (2) поле, которое пайплайн намеренно не заполнял (напр. work authorization/
    demographic — §3 НЕ авто), но сайт требует его как нативный HTML required —
    ловим постфактум через :invalid после клика; (3) то же самое, но валидация
    целиком на JS без HTML5 constraint API (custom react-select и подобные
    виджеты, без атрибута required вообще) — ловим через [aria-invalid="true"]
    (см. _invalid_fields_signal, подтверждено на живом ATS 23.07.2026, не
    теоретический случай). Какой именно сигнал сработал — в failure_signal.

    Вторая часть того же инцидента — доказательство УСПЕХА. Этот метод —
    единственный производитель пяти сигналов, из которых finalize_confirmed
    складывает долговечное доказательство (см. submission_proof_missing):
    click_performed (клик физически выполнен), errors_absent (ошибок нет),
    form_absent (отправленной формы на странице больше нет — по подписи, снятой
    до клика), confirmation_signal (утвердительная фраза завершённой подачи в
    видимом заголовке/статус-регионе; сменившийся URL с токеном подтверждения в
    path лишь уточняет метку и сам по себе не доказывает) и screenshot_path. Всё,
    что видно на странице, читается ОДНИМ согласованным снимком живого документа:
    мёртвый handle прежней формы отвечает «всё чисто» на любой странице, то есть
    не отвечает ничего. Любой неустановленный сигнал остаётся отрицательным:
    недоказанная подача уходит в unknown, что чинится руками, а ложно
    доказанная — нет.

    Вердикт `submitted` этот метод НЕ выставляет: браузер-воркер сообщает
    наблюдения, а порог доказательства держит finalize_confirmed
    (submission_proof_missing) слоем выше. Поле остаётся на дефолте модели.
    """
    await _dismiss_cookie_banner(page)
    fill_result = await fill_form(page, fields, resume_path=resume_path,
                                  consent_checks=consent_checks)
    if fill_result.unmatched:
        if screenshot_path:
            await page.screenshot(path=screenshot_path)
        # Кнопку не жали: все сигналы доказательства честно отрицательны
        # (дефолты модели — False/None), а не «не установлены».
        return SubmitResult(confirmation_url=page.url,
                            screenshot_path=screenshot_path,
                            unmatched=fill_result.unmatched,
                            failure_signal="unmatched")

    # <button> без явного type по спецификации HTML — тоже submit (частый случай на
    # Ashby/Greenhouse React-формах); исключаем только заведомо не-submit type.
    btn = page.locator(
        "button:not([type='button']):not([type='reset']), input[type='submit']"
    ).first
    # Handle на форму снимаем ДО клика, пока элемент точно живой; после реальной
    # навигации он сам протухнет — это и есть сигнал "страница ушла" в _invalid_fields_signal.
    form_handle = await btn.evaluate_handle("btn => btn.closest('form') || document")
    signature = await _form_signature(form_handle)
    url_before = page.url
    await btn.click()
    # Клик — свершившийся факт внешнего действия: фиксируем ДО любых проверок
    # результата и независимо от того, чем всё кончилось (иначе «неизвестный
    # исход» неотличим от «кнопку не жали», а это разные состояния заявки).
    click_performed = True
    # Сначала дождаться, пока исход вообще появится: networkidle сам по себе
    # возвращается мгновенно, пока сайт ещё не начал свой запрос (см.
    # _wait_for_submit_outcome — живой инцидент OKX 08.08.2026).
    await _wait_for_submit_outcome(page, signature, url_before)
    try:
        await page.wait_for_load_state("networkidle", timeout=15_000)
    except Exception:  # noqa: BLE001 — таймаут навигации не фатален
        pass
    confirmation_url = page.url
    if screenshot_path:
        await page.screenshot(path=screenshot_path)
    signal = await _invalid_fields_signal(form_handle)
    snapshot = await _page_snapshot(page, signature)
    if (signal is None and snapshot is not None
            and _looks_like_email_verification(snapshot.get("text"))):
        signal = "email_verification_required"
    # Ошибки — конъюнкция обеих проверок (форма до клика и живой документ после):
    # мёртвый handle отвечает «чисто» всегда, снимок этого не знает.
    errors_absent = (signal is None and snapshot is not None
                     and not snapshot["errors_present"])
    # Формы нет — только если известно, ЧТО искать (без подписи доказать её
    # отсутствие нечем) и если на странице не осталось неопознанной формы
    # анкетного размера: сервер мог сменить идентичность формы целиком, и тогда
    # «не нашёл свою» неотличимо от «формы нет».
    form_absent = (signature is not None and snapshot is not None
                   and not snapshot["form_present"]
                   and not snapshot["unidentified_form_present"])
    # Подтверждение ищем только если форма ушла и ошибок нет: на странице с
    # видимой ошибкой валидации «спасибо»-текст был бы обманом.
    confirmation_signal = (_confirmation_signal(snapshot, url_before, confirmation_url)
                           if errors_absent and form_absent else None)
    return SubmitResult(click_performed=click_performed,
                        confirmation_url=confirmation_url,
                        confirmation_signal=confirmation_signal,
                        form_absent=form_absent,
                        errors_absent=errors_absent,
                        screenshot_path=screenshot_path, failure_signal=signal)
