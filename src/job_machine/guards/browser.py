from job_machine.browser.blockers import HUMAN_RETRYABLE_BLOCKERS
from job_machine.guards.base import Decision, Guard, GuardResult, NextAction
from job_machine.guards import registry

# Контракт browser_state (наполняет Playwright-воркер среза 2):
#   {
#     "url": str,
#     "captcha": bool, "mfa": bool, "login_wall": bool,
#     "account_required": bool, "anti_bot": bool, "ambiguous_submit": bool,
#   }
# Любой отсутствующий флаг трактуется как False. Порядок проверки = приоритет.
# Метки captcha/mfa/account_required/login_wall/anti_bot — из общего словаря
# browser.blockers.HUMAN_RETRYABLE_BLOCKERS (то же имя блокера, что и в
# fill/service.py::resume_after_handoff — единый источник истины).
_BLOCKER_ORDER = HUMAN_RETRYABLE_BLOCKERS + ("ambiguous_submit",)

_NEXT_ACTION = {blocker: NextAction.HUMAN_BROWSER_TAKEOVER for blocker in HUMAN_RETRYABLE_BLOCKERS}
_NEXT_ACTION["ambiguous_submit"] = NextAction.ASK_USER


class BrowserBlockerDetector(Guard):
    """Классифицирует browser_state в один типизированный блокер.

    CAPTCHA/anti-bot НЕ обходятся (§19 ТЗ) — только пауза + human takeover.
    """

    name = "BrowserBlockerDetector"
    stage = "inspect_fill"

    def check(self, ctx) -> GuardResult:
        state = ctx.browser_state or {}
        blocker = self._classify(state)
        if blocker is None:
            return GuardResult(self.name, self.stage, Decision.CONTINUE)
        return GuardResult(
            self.name, self.stage, Decision.STOP,
            next_action=_NEXT_ACTION[blocker],
            reason=f"browser blocker: {blocker}",
            input_refs={"url": state.get("url")},
        )

    @staticmethod
    def _classify(state: dict) -> str | None:
        for blocker in _BLOCKER_ORDER:
            if state.get(blocker):
                return blocker
        return None


def register_all(reg=registry.DEFAULT) -> None:
    reg.register(BrowserBlockerDetector())
