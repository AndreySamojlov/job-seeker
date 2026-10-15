from job_machine.guards.base import Decision, NextAction
from job_machine.guards.context import GuardContext
from job_machine.guards.browser import BrowserBlockerDetector


def _ctx(state):
    return GuardContext(browser_state=state)


def test_no_blocker_continue():
    r = BrowserBlockerDetector().check(_ctx({"url": "https://x", "ambiguous_submit": False}))
    assert r.decision is Decision.CONTINUE


def test_empty_state_continue():
    r = BrowserBlockerDetector().check(_ctx({}))
    assert r.decision is Decision.CONTINUE


def test_none_state_continue():
    r = BrowserBlockerDetector().check(GuardContext(browser_state=None))
    assert r.decision is Decision.CONTINUE


def test_captcha_stops_with_takeover():
    r = BrowserBlockerDetector().check(_ctx({"captcha": True, "url": "https://x"}))
    assert r.decision is Decision.STOP
    assert r.next_action is NextAction.HUMAN_BROWSER_TAKEOVER
    assert "captcha" in r.reason


def test_mfa_stops_with_takeover():
    r = BrowserBlockerDetector().check(_ctx({"mfa": True}))
    assert r.decision is Decision.STOP
    assert r.next_action is NextAction.HUMAN_BROWSER_TAKEOVER


def test_login_wall_stops_with_takeover():
    r = BrowserBlockerDetector().check(_ctx({"login_wall": True}))
    assert r.decision is Decision.STOP
    assert r.next_action is NextAction.HUMAN_BROWSER_TAKEOVER


def test_account_required_stops_with_takeover():
    r = BrowserBlockerDetector().check(_ctx({"account_required": True}))
    assert r.decision is Decision.STOP
    assert r.next_action is NextAction.HUMAN_BROWSER_TAKEOVER


def test_ambiguous_submit_asks_user():
    r = BrowserBlockerDetector().check(_ctx({"ambiguous_submit": True}))
    assert r.decision is Decision.STOP
    assert r.next_action is NextAction.ASK_USER


def test_precedence_captcha_over_ambiguous():
    r = BrowserBlockerDetector().check(_ctx({"captcha": True, "ambiguous_submit": True}))
    assert "captcha" in r.reason
