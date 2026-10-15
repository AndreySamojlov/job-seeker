"""Извлечение сигналов страницы и generic form_schema (без ATS-специфики).

ATS-специфика (Greenhouse-адаптер) — план 5; здесь только обобщённый разбор DOM.
"""

from job_machine.browser.schema import FormField, FormSchema
from job_machine.consent import looks_like_consent


_CAPTCHA_WIDGET_SELECTOR = (
    "iframe[src*='recaptcha'], iframe[src*='hcaptcha'], .g-recaptcha, .h-captcha"
)
_CAPTCHA_CHALLENGE_SELECTOR = "iframe[src*='bframe'], iframe[src*='frame=challenge']"
_FILLABLE_FIELD_SELECTOR = (
    "input:not([type='hidden']):not([type='submit']):not([type='button']), "
    "select, textarea"
)


def _is_invisible_marker(src, data_size):
    """True если src/data-size явно помечает виджет как invisible (v3/enterprise скоринг).

    Живой инцидент 07.07.2026 (Monks, application_id 4bf09f34-...): reCAPTCHA
    enterprise-iframe присутствует в DOM всегда (бейдж "protected by reCAPTCHA",
    src содержит size=invisible) даже когда решать нечего — фоновый скоринг
    поведения, не видимый челлендж.
    """
    if src and "invisible" in src:
        return True
    return (data_size or "").strip().lower() == "invisible"


async def _has_visible_captcha(page):
    """True только для реально видимого CAPTCHA-челленджа, не фонового скоринга.

    Обычный видимый v2-чекбокс — блокер сразу (см. _is_invisible_marker). Отдельный
    челлендж-фрейм (reCAPTCHA bframe / hCaptcha frame=challenge) — вендоры
    (подтверждено на живом hcaptcha.com 07.07.2026: computed style challenge-iframe
    visibility:hidden) преднагружают его в DOM ВСЕГДА, пока риск-скоринг не
    эскалирует до реального челленджа — поэтому одного присутствия недостаточно,
    нужна реальная видимость (is_visible()).
    """
    widgets = page.locator(_CAPTCHA_WIDGET_SELECTOR)
    for i in range(await widgets.count()):
        el = widgets.nth(i)
        src = await el.get_attribute("src")
        data_size = await el.get_attribute("data-size")
        if not _is_invisible_marker(src, data_size):
            return True
    challenge = page.locator(_CAPTCHA_CHALLENGE_SELECTOR)
    for i in range(await challenge.count()):
        if await challenge.nth(i).is_visible():
            return True
    return False


async def extract_signals(page, http_status=None):
    """Собрать булевы признаки страницы для classify_page()."""

    async def present(selector):
        return await page.locator(selector).count() > 0

    text = (await page.content()).lower()
    real_fields = page.locator(_FILLABLE_FIELD_SELECTOR)
    return {
        "http_status": http_status,
        "has_captcha": await _has_visible_captcha(page),
        "has_login_form": await present("input[type='password']"),
        "has_mfa_prompt": "verification code" in text or "one-time code" in text,
        "has_account_creation": "create account" in text or "sign up" in text,
        "has_anti_bot_interstitial": "just a moment" in text
        or "checking your browser" in text,
        "form_count": await page.locator("form").count(),
        "real_field_count": await real_fields.count(),
        "final_url": page.url,
    }


async def follow_apply_link_if_present(page) -> bool:
    """Если на странице есть ссылка/кнопка вида 'Apply...' (Lever-style landing page,
    где сама форма — на отдельном /apply URL), перейти по её href ОДИН раз.

    Переходим через page.goto(href), а не .click() — так не завязываемся на
    возможный target="_blank" (новая вкладка вместо навигации той же страницы).

    Кандидатов может быть несколько (напр. декой-кнопка "Apply with LinkedIn" ПЕРЕД
    настоящей ссылкой "Apply for this job" в document order) — .first брал бы первый
    DOM-матч независимо от селектор-ветки (a vs button), а у голой <button> нет
    .href-свойства. Поэтому перебираем ВСЕХ кандидатов по порядку и берём первого
    с реальным href, а не первого совпавшего элемента.

    Возвращает True, если перешли (вызывающий обязан заново вызвать extract_signals +
    classify_page на обновлённой странице); False — подходящей ссылки нет.
    """
    candidates = page.locator("a:has-text('apply'), button:has-text('apply')")
    count = await candidates.count()
    for i in range(count):
        href = await candidates.nth(i).evaluate("e => e.href")
        if href:
            await page.goto(href, wait_until="domcontentloaded", timeout=30_000)
            return True
    return False


async def wait_for_fillable_content(page, timeout_ms: int = 5000) -> None:
    """Дождаться, пока на странице появится реальная форма (<form> или хотя бы одно
    заполняемое поле) — некоторые SPA (Ashby и подобные) дорисовывают форму
    асинхронно уже ПОСЛЕ domcontentloaded, и мгновенный снимок сигналов застаёт
    ещё пустую страницу (form_count=0, real_field_count=0).

    wait_for_selector, а не wait_for_function: у ряда ATS (подтверждено на живом
    Ashby, 2026-07-17) строгий CSP script-src без 'unsafe-eval' блокирует
    wait_for_function (EvalError) — исключение тихо проглатывалось, функция
    фактически не ждала. wait_for_selector использует другой CDP-механизм
    (поиск по DOM-дереву, не JS-eval) и CSP не подвержен.

    Тихо не делает ничего при таймауте — вызывающий всё равно пере-классифицирует
    по актуальным на тот момент сигналам; таймаут здесь означает лишь "не помогло",
    не фатальная ошибка.
    """
    combined_selector = "form, " + _FILLABLE_FIELD_SELECTOR
    try:
        await page.wait_for_selector(combined_selector, timeout=timeout_ms, state="attached")
    except Exception:  # noqa: BLE001 — таймаут не фатален
        pass


# Заглушка React Select: input, который несёт required, но не имеет ни name, ни id
# (живая разметка job-boards.greenhouse.io, снята 2026-08-06). Лейбл вопроса при этом
# сидит на СОСЕДНЕМ input[role=combobox]. Ищем этого соседа вверх по предкам, чтобы
# перенести требуемость на лейблованную половину.
#
# Привязка структурная, а не по классу: на живой странице заглушка имеет класс вида
# "remix-css-1a0ro4n-requiredInput" — это сгенерированный CSS-in-JS хеш, он меняется
# между деплоями Greenhouse и опорой быть не может.
#
# Подъём ограничен: не выше <form> и не глубже _SHELL_LOOKUP_MAX_DEPTH уровней, и
# контейнер обязан содержать РОВНО ОДИН combobox. Иначе на форме с единственным
# комбобоксом любой безымянный required-инпут (напр. внутренность стороннего виджета)
# ложно присвоил бы себе чужой вопрос.
_SHELL_LOOKUP_MAX_DEPTH = 5

_REQUIRED_SHELL_OWNER_JS = """el => {
  if (el.name || el.id) return null;
  let node = el.parentElement;
  for (let depth = 0; node && depth < %d; depth += 1) {
    if (node.tagName === 'FORM') break;
    const boxes = node.querySelectorAll('input[role="combobox"][id]');
    if (boxes.length === 1) return boxes[0].id;
    if (boxes.length > 1) return null;
    node = node.parentElement;
  }
  return null;
}""" % _SHELL_LOOKUP_MAX_DEPTH


async def extract_form_schema(page):
    """Извлечь обобщённую схему формы со страницы."""
    inputs = page.locator(_FILLABLE_FIELD_SELECTOR)
    count = await inputs.count()
    fields = []
    by_name = {}
    file_inputs = []
    consent_checkboxes = []
    for i in range(count):
        el = inputs.nth(i)
        tag = await el.evaluate("e => e.tagName.toLowerCase()")
        if tag == "select":
            ftype = "select"
        elif tag == "textarea":
            ftype = "textarea"
        else:
            ftype = (await el.get_attribute("type")) or "text"
        name = (
            (await el.get_attribute("name"))
            or (await el.get_attribute("id"))
            or f"field_{i}"
        )
        required = await el.evaluate("e => e.required === true")
        if required and name.startswith("field_"):
            owner = await el.evaluate(_REQUIRED_SHELL_OWNER_JS)
            if owner is not None and owner in by_name:
                # Требуемость принадлежит вопросу, а не заглушке: переносим её на
                # лейблованную половину и саму заглушку в схему не отдаём.
                by_name[owner].required = True
                continue
        label = await _label_for(page, el)
        options = []
        if tag == "select":
            options = [t.strip() for t in await el.locator("option").all_inner_texts()]
        group_label = None
        if ftype == "checkbox":
            group_label = await _group_label_for(el, label)
        field = FormField(
            name=name,
            field_type=ftype,
            label=label,
            group_label=group_label,
            required=required,
            options=options,
        )
        fields.append(field)
        by_name.setdefault(name, field)
        if ftype == "file":
            file_inputs.append(name)
        if ftype == "checkbox" and label and looks_like_consent(label):
            consent_checkboxes.append(name)
    return FormSchema(
        url=page.url,
        fields=fields,
        file_inputs=file_inputs,
        consent_checkboxes=consent_checkboxes,
        submit_buttons=await _submit_candidates(page),
    )


async def _label_for(page, el):
    """Текст <label for=id>, иначе aria-label/placeholder, иначе None."""
    el_id = await el.get_attribute("id")
    if el_id:
        lbl = page.locator(f"label[for='{el_id}']")
        if await lbl.count() > 0:
            return (await lbl.first.inner_text()).strip()
    return await el.get_attribute("aria-label") or await el.get_attribute("placeholder")


async def _group_label_for(el, own_label):
    """Текст question-level label (fieldset/legend или сосед перед контейнером), не
    per-option label. None если ничего не нашли (§3: молчание = статус-кво).

    Только legend + sibling-walk (никакого "любой другой label в контейнере"
    фолбэка) — такой фолбэк комбинировался с широким CSS-селектором контейнера
    ([class*="field"] может смэтчить секцию с НЕСКОЛЬКИМИ вопросами) и мог
    приписать чекбоксу label СОСЕДНЕГО вопроса (code-review finding, 2026-07-15).
    Boundary-check при sibling-walk останавливается и на самом prev будучи
    голым form-control'ом (не только когда он СОДЕРЖИТ form-control) — иначе
    walk мог перешагнуть через одиночный <input> без обёртки к чужому label."""
    return await el.evaluate(
        """(node, ownLabel) => {
            const norm = s => (s || '').replace(/\\s+/g, ' ').trim();
            const own = norm(ownLabel);
            const boundaryTags = ['FIELDSET', 'INPUT', 'SELECT', 'TEXTAREA'];
            const container = node.closest('fieldset, [class*="field"], [class*="question"]');
            if (!container) return null;
            const legend = container.querySelector('legend');
            if (legend && norm(legend.innerText) && norm(legend.innerText) !== own)
                return norm(legend.innerText);
            let prev = container.previousElementSibling;
            while (prev) {
                if (prev.tagName === 'LABEL' && norm(prev.innerText)) return norm(prev.innerText);
                if (boundaryTags.includes(prev.tagName) || prev.querySelector('input, select, textarea'))
                    break;
                prev = prev.previousElementSibling;
            }
            return null;
        }""",
        own_label,
    )


async def _submit_candidates(page):
    """Тексты кнопок-кандидатов на submit (для detect_pre_submit плана 5).

    Тот же локатор, что и submit_form (fill.py) — <button> без явного type тоже
    submit по спецификации HTML (частый случай на Ashby/Greenhouse), иначе
    disclosed-summary не совпадает с тем, что реально кликнет submit_form.
    """
    loc = page.locator(
        "button:not([type='button']):not([type='reset']), input[type='submit']"
    )
    out = []
    for i in range(await loc.count()):
        el = loc.nth(i)
        tag = await el.evaluate("e => e.tagName.toLowerCase()")
        if tag == "button":
            text = (await el.inner_text()).strip()
        else:
            text = await el.get_attribute("value") or ""
        out.append(text or "submit")
    return out
