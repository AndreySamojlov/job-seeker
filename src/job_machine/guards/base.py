from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from job_machine.guards.context import GuardContext


class Decision(Enum):
    CONTINUE = "continue"
    STOP = "stop"
    ROLLBACK = "rollback"
    REQUIRE_USER_INPUT = "require_user_input"
    REQUIRE_APPROVAL = "require_approval"


class NextAction(Enum):
    ASK_USER = "ask_user"
    RETRY_LATER = "retry_later"
    MANUAL_REVIEW = "manual_review"
    HUMAN_BROWSER_TAKEOVER = "human_browser_takeover"
    SKIP_VACANCY = "skip_vacancy"
    ADD_ADAPTER_RULE = "add_adapter_rule"
    ADD_ANSWER_VAULT_ENTRY = "add_answer_vault_entry"
    UPDATE_EVIDENCE_CLAIM = "update_evidence_claim"
    ESCALATE_TO_DEBUG = "escalate_to_debug"
    NONE = "none"


@dataclass(frozen=True)
class GuardResult:
    guard_name: str
    stage: str
    decision: Decision
    next_action: NextAction = NextAction.NONE
    reason: str | None = None
    payload_hash: str | None = None
    input_refs: dict = field(default_factory=dict)
    normalizations: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.decision is Decision.CONTINUE


class Guard(ABC):
    """Детерминированный guard: без LLM и без сети, читает только GuardContext.

    Никогда молча не меняет critical payload — любая нормализация уходит в
    GuardResult.normalizations.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Уникальное имя guard'а (ключ реестра). Подкласс задаёт как class-атрибут."""

    @property
    @abstractmethod
    def stage(self) -> str:
        """Стадия конвейера, к которой относится guard."""

    @abstractmethod
    def check(self, ctx: "GuardContext") -> GuardResult: ...
