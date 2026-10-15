from job_machine.ats.urlnorm import (
    confirmation_mismatch,
    identified_post,
    normalize_apply_url,
    post_identity,
    same_post,
)


def test_normalize_strips_query_fragment_slash_and_lowercases_host():
    assert normalize_apply_url("HTTPS://Boards.Greenhouse.io/acme/jobs/1/?gh_src=x#top") == \
        "https://boards.greenhouse.io/acme/jobs/1"


def test_gh_identity_ignores_host_variant_and_region():
    urls = [
        "https://boards.greenhouse.io/acme/jobs/123",
        "https://job-boards.greenhouse.io/acme/jobs/123",
        "https://job-boards.eu.greenhouse.io/acme/jobs/123",
    ]
    assert {post_identity(u) for u in urls} == {"gh:acme:123"}


def test_gh_identity_ignores_path_suffix_and_query():
    assert post_identity(
        "https://job-boards.greenhouse.io/acme/jobs/123/confirmation?utm=1"
    ) == "gh:acme:123"


def test_gh_embed_identity():
    assert post_identity(
        "https://boards.greenhouse.io/embed/job_app?for=acme&token=123"
    ) == "gh:acme:123"


def test_different_job_ids_are_different_posts():
    assert not same_post(
        "https://job-boards.greenhouse.io/remotecom/jobs/7778870003",
        "https://job-boards.greenhouse.io/remotecom/jobs/7778884003")


def test_same_post_across_hosts():
    assert same_post(
        "https://boards.greenhouse.io/figma/jobs/5982942004",
        "https://job-boards.greenhouse.io/figma/jobs/5982942004")


def test_non_greenhouse_falls_back_to_normalized_url():
    assert post_identity("https://jobs.ashbyhq.com/co/abc-123/") == \
        "https://jobs.ashbyhq.com/co/abc-123"
    assert same_post("https://x.io/apply?a=1", "https://x.io/apply")
    assert not same_post("https://x.io/apply/1", "https://x.io/apply/2")


def test_identified_post_only_for_parsed_ats_urls():
    assert identified_post("https://job-boards.greenhouse.io/acme/jobs/1")
    assert identified_post("https://boards.greenhouse.io/embed/job_app?for=acme&token=1")
    assert not identified_post("https://acme/thanks")  # generic — пост не идентифицирован
    assert not identified_post("https://boards.greenhouse.io/acme")  # gh-хост без job id


def test_confirmation_mismatch_requires_both_posts_identified():
    dest = "https://boards.greenhouse.io/acme/jobs/1"
    # оба идентифицированы, разные посты → mismatch
    assert confirmation_mismatch("https://job-boards.greenhouse.io/acme/jobs/2", dest)
    # тот же пост (другой хост/суффикс) → нет mismatch
    assert not confirmation_mismatch(
        "https://job-boards.greenhouse.io/acme/jobs/1/confirmation", dest)
    # generic thanks-URL не идентифицирует пост → нет mismatch (не шумим)
    assert not confirmation_mismatch("https://acme.example/thanks", dest)
    # пустой confirmation → сравнивать нечего
    assert not confirmation_mismatch(None, dest)
    assert not confirmation_mismatch("", dest)
