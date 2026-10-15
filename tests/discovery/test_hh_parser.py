"""Тесты regex-парсера hh.ru search-results (data-qa атрибуты, снятые live 2026-07-17)."""

from job_machine.discovery.hh_parser import parse_search_results

# Урезанная, но структурно точная карточка — снята с реальной страницы поиска
# hh.ru/search/vacancy (см. docs/superpowers/specs/2026-07-17-hh-ru-sourcing-design.md §2)
_CARD = '''
<div data-qa="vacancy-serp__vacancy" class="magritte-card">
  <div id="135084322" class="vacancy-card">
    <a data-qa="serp-item__title" href="https://hh.ru/vacancy/135084322?query=Engineering+Manager&amp;hhtmFrom=vacancy_search_list" target="_blank">
      <span data-qa="serp-item__title-text">AI Product Manager</span>
    </a>
    <div class="compensation-labels">
      <span data-qa="vacancy-label-work-schedule-remote">Можно удалённо</span>
    </div>
    <a data-qa="vacancy-serp__vacancy-employer" href="/employer/1469299">
      <span data-qa="vacancy-serp__vacancy-employer-text">Valletta.Software</span>
    </a>
    <span data-qa="vacancy-serp__vacancy-address">Мальта</span>
  </div>
</div>
'''

_CARD_NO_REMOTE_BADGE = '''
<div data-qa="vacancy-serp__vacancy" class="magritte-card">
  <div id="999" class="vacancy-card">
    <a data-qa="serp-item__title" href="https://hh.ru/vacancy/999?query=QA">
      <span data-qa="serp-item__title-text">Onsite QA</span>
    </a>
    <a data-qa="vacancy-serp__vacancy-employer" href="/employer/2">
      <span data-qa="vacancy-serp__vacancy-employer-text">SomeCorp</span>
    </a>
    <span data-qa="vacancy-serp__vacancy-address">Ереван</span>
  </div>
</div>
'''


def test_parses_title_url_company_location_remote():
    jobs = parse_search_results(_CARD)
    assert len(jobs) == 1
    job = jobs[0]
    assert job.title == "AI Product Manager"
    assert job.url == "https://hh.ru/vacancy/135084322?query=Engineering+Manager&hhtmFrom=vacancy_search_list"
    assert job.company_name == "Valletta.Software"
    assert job.location == "Мальта"
    assert job.is_remote is True


def test_card_without_remote_badge_is_not_remote():
    jobs = parse_search_results(_CARD_NO_REMOTE_BADGE)
    assert len(jobs) == 1
    assert jobs[0].is_remote is False


def test_multiple_cards_parsed_independently():
    jobs = parse_search_results(_CARD + _CARD_NO_REMOTE_BADGE)
    assert len(jobs) == 2
    assert {j.company_name for j in jobs} == {"Valletta.Software", "SomeCorp"}


def test_empty_html_returns_empty_list():
    assert parse_search_results("") == []


def test_html_with_no_cards_returns_empty_list():
    assert parse_search_results("<html><body>no results</body></html>") == []


_CARD_WITH_HIGHLIGHTED_TITLE = '''
<div data-qa="vacancy-serp__vacancy" class="magritte-card">
  <div id="777" class="vacancy-card">
    <a data-qa="serp-item__title" href="https://hh.ru/vacancy/777">
      <span data-qa="serp-item__title-text">AI <mark>Product</mark> Manager</span>
    </a>
    <a data-qa="vacancy-serp__vacancy-employer" href="/employer/3">
      <span data-qa="vacancy-serp__vacancy-employer-text">Acme</span>
    </a>
    <span data-qa="vacancy-serp__vacancy-address">Cyprus</span>
  </div>
</div>
'''


def test_title_with_nested_highlight_markup_is_not_truncated():
    jobs = parse_search_results(_CARD_WITH_HIGHLIGHTED_TITLE)
    assert len(jobs) == 1
    assert jobs[0].title == "AI Product Manager"
