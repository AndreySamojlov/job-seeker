"""Read the current form without navigation, filling, validation events or clicks.

This is structural readiness, not proof of factual answers or approval. Custom
required widgets that cannot be verified generically fail closed.
"""
from job_machine.browser.blockers import classify_page
from job_machine.browser.inspect import extract_signals


async def inspect_readiness(page) -> dict:
    url = page.url
    blocker = classify_page(await extract_signals(page))
    if blocker:
        return {'ready': False, 'url': url, 'blocker': blocker}
    result = await page.evaluate('''() => {
      const visible = e => e.getClientRects().length > 0 &&
          getComputedStyle(e).visibility !== 'hidden';
      const forms = [...document.forms].filter(visible);
      if (forms.length !== 1) return {ready:false, blocker:'ambiguous_form'};
      const form = forms[0];
      if (!form.querySelector('input,select,textarea'))
          return {ready:false, blocker:'no_fields'};
      const fields = [...form.elements];
      if (fields.some(e => e.willValidate && !e.validity.valid))
          return {ready:false, blocker:'native_invalid'};
      if ([...form.querySelectorAll('[aria-invalid="true"]')].some(visible))
          return {ready:false, blocker:'aria_invalid'};
      if ([...form.querySelectorAll('[aria-required="true"]')].some(e =>
          visible(e) && (!e.matches('input,select,textarea') ||
          (['checkbox','radio'].includes(e.type) ? !e.checked : !e.value))))
          return {ready:false, blocker:'custom_required_unverified'};
      return {ready:true, blocker:null};
    }''')
    if page.url != url:
        return {'ready': False, 'url': page.url, 'blocker': 'page_changed'}
    return {**result, 'url': url}
