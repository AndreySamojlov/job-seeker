from types import SimpleNamespace as NS
from uuid import uuid4


def test_only_allowed_locked_qualification_and_source_caveats(monkeypatch):
    from job_machine.fit import facts
    monkeypatch.setattr(facts, 'load_claims', lambda *a: [NS(claim_id='c', claim_text='Synthetic', status='approximate', safe_use='Caveat')])
    monkeypatch.setattr(facts, 'load_cloud', lambda *a: NS(positions=[], skills=[], achievements=[]))
    monkeypatch.setattr(facts, 'load_answers', lambda *a: [NS(field=k, value=v, state=s) for k,v,s in [('Degree','Synthetic degree','locked'), ('email','secret','locked'), ('license','secret','blocked'), ('other','secret','locked')]])
    value = facts.build_fit_input(None, candidate_id='synthetic', vacancy_id=uuid4(), job_text='Job', answer_allowlist={' degree ', 'email', 'license'})
    assert len(value.facts) == 2
    assert value.facts[0].status == 'approximate'
    assert 'Caveat' in value.facts[0].text
    assert 'secret' not in repr(value)


def test_canonical_names_do_not_collapse_non_ascii_fields():
    from job_machine.fit.facts import canonical_field
    assert canonical_field('  Уровень-образования ') == 'уровень_образования'
    assert canonical_field('姓名') != canonical_field('学位')


def test_claim_proof_is_preserved_with_status_and_safe_use(monkeypatch):
    from job_machine.fit import facts
    monkeypatch.setattr(facts, 'load_claims', lambda *a: [NS(
        claim_id='c-proof', claim_text='Synthetic claim', status='verified',
        proof='Synthetic proof', safe_use='Synthetic caveat',
    )])
    monkeypatch.setattr(facts, 'load_cloud', lambda *a: NS(positions=[], skills=[], achievements=[]))
    monkeypatch.setattr(facts, 'load_answers', lambda *a: [])
    result = facts.build_fit_input(None, candidate_id='synthetic', vacancy_id=uuid4(), job_text='Job')
    fact = result.facts[0]
    assert fact.status == 'verified'
    assert 'Synthetic proof' in fact.text
    assert 'Synthetic caveat' in fact.text
