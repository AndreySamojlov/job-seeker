"""Build assessment inputs from explicitly permitted evidence sources only."""
import re
import unicodedata
from job_machine.package.store import load_answers
from job_machine.triage.store import load_claims
from job_machine.cloud.store import load_cloud
from .models import FitFact, FitInput


def canonical_field(value):
    return re.sub(r'[^\w]+', '_', unicodedata.normalize('NFKC', value).casefold()).strip('_')


# Even configuration cannot turn identity/consent/preferences into qualifications.
_PRIVATE = {'name','first_name','last_name','full_name','email','phone','address','contact','contacts','consent','gdpr','privacy','salary','preferences','preference','search_profile','searchprofile','linkedin','website','work_mode','relocation','location','desired_role','имя','фамилия','телефон','почта','согласие','предпочтения'}


def build_fit_input(conn, *, candidate_id, vacancy_id, job_text, answer_allowlist=()):
    facts = []
    def add(key, text, status, source, caveat=''):
        facts.append(FitFact(key, text + (f'\nSafe use: {caveat}' if caveat else ''), status if status in {'verified','approximate','unknown'} else 'unknown', source))
    for c in sorted(load_claims(conn, candidate_id), key=lambda x: x.claim_id):
        evidence = c.claim_text
        if getattr(c, 'proof', None):
            evidence += f'\nProof: {c.proof}'
        add('claim:' + c.claim_id, evidence, c.status, 'claims', c.safe_use)
    cloud = load_cloud(conn, candidate_id)
    for p in sorted(cloud.positions, key=lambda x: x.pid):
        add('position:' + p.pid, f'{p.company}; {p.title}; {p.start}–{p.end}; {p.summary}', 'unknown', 'experience_cloud')
    for a in sorted(cloud.achievements, key=lambda x: x.aid):
        add('achievement:' + a.aid, f'{a.text}; {a.metric}; claims: {a.claims}', a.status, 'experience_cloud', a.safe_use)
    for s in sorted(cloud.skills, key=lambda x: x.name):
        add('skill:' + s.name, f'{s.name}; {s.category}; {s.framing}; {s.evidence}', 'unknown', 'experience_cloud', s.safe_use)
    allowed = {canonical_field(k) for k in answer_allowlist}
    for a in sorted(load_answers(conn, candidate_id), key=lambda x: (canonical_field(x.field), x.value)):
        field = canonical_field(a.field)
        if (field and field in allowed and not (_PRIVATE & set(field.split('_'))) and field not in _PRIVATE
                and a.state == 'locked' and a.value.strip().casefold() not in {'', 'unknown', 'none', 'n/a', 'null', '?', 'неизвестно'}):
            add('answer:' + field, f'{field}: {a.value}', 'verified', 'locked_qualification')
    return FitInput(candidate_id, vacancy_id, job_text, tuple(facts))
