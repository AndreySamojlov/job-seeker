from job_machine.resume.headline import headline_for_role


def test_qa_role():
    assert "QA" in headline_for_role("andrey-s", "Senior QA Engineer", fallback="X")


def test_delivery_role():
    h = headline_for_role("andrey-s", "IT Delivery Manager", fallback="X")
    assert "Delivery" in h


def test_unknown_role_falls_back():
    assert headline_for_role("andrey-s", "Ninja Guru", fallback="FB / TB") == "FB / TB"


def test_none_role_falls_back():
    assert headline_for_role("andrey-s", None, fallback="FB") == "FB"


def test_candidate_without_config_always_falls_back():
    # daria-b (и любой кандидат без записей в конфиге) никогда не получает канную
    # фразу — даже если роль дословно совпадает с ключевыми словами andrey-s. Это
    # основной regression-тест на баг 1 (утечка чужого заголовка, §3).
    h = headline_for_role("daria-b", "Senior QA Engineer", fallback="Senior Test Engineer")
    assert h == "Senior Test Engineer"


def test_unknown_candidate_id_falls_back():
    h = headline_for_role("nonexistent-candidate", "IT Delivery Manager", fallback="FB")
    assert h == "FB"


def test_project_manager_role_no_longer_falls_back():
    h = headline_for_role("andrey-s", "Senior Project Manager - Technical Services",
                          fallback="FB / TB")
    assert h == "IT Delivery Leader / Program Manager"


def test_product_lead_role_matches_product_bucket():
    h = headline_for_role("andrey-s", "Product Lead (UK)", fallback="FB / TB")
    assert h == "IT Delivery Leader / Product Delivery Lead"


def test_engineering_team_lead_matches_team_lead_not_engineering_manager():
    h = headline_for_role("andrey-s", "Software Engineering Team Lead", fallback="FB / TB")
    assert h == "IT Delivery Leader / Team Lead"


def test_delivery_manager_role_maps_to_delivery_bucket_not_program():
    h = headline_for_role("andrey-s", "Delivery Manager", fallback="FB / TB")
    assert h == "IT Delivery Leader / Delivery Manager"


def test_engineering_manager_role_still_matches_em_bucket():
    h = headline_for_role("andrey-s", "Engineering Manager, Email", fallback="FB / TB")
    assert h == "Engineering Manager / Delivery Leader"


def test_tiebreak_prefers_longer_matched_phrase_support_over_team_lead():
    h = headline_for_role("andrey-s", "Support Team Lead", fallback="FB / TB")
    assert h == "IT Delivery Leader / Team Lead"


def test_tiebreak_prefers_longer_matched_phrase_solutions_over_team_lead():
    h = headline_for_role("andrey-s", "Team Lead, Solutions Consultant", fallback="FB / TB")
    assert h == "IT Delivery Leader / Support & Solutions Lead"


def test_multiple_matched_keywords_in_one_bucket_beats_single_match_elsewhere():
    h = headline_for_role("andrey-s", "Senior Quality Test Program Coordinator",
                          fallback="FB / TB")
    assert h == "Head of QA / Quality Engineering Leader"
