from job_machine.guards.base import Guard


class Registry:
    """Реестр guards name -> Guard."""

    def __init__(self):
        self._guards: dict[str, Guard] = {}

    def register(self, guard: Guard) -> Guard:
        if guard.name in self._guards:
            raise ValueError(f"guard already registered: {guard.name}")
        self._guards[guard.name] = guard
        return guard

    def get(self, name: str) -> Guard:
        try:
            return self._guards[name]
        except KeyError:
            raise KeyError(f"guard not registered: {name}")

    def all_guards(self) -> dict[str, Guard]:
        return dict(self._guards)


# Глобальный реестр по умолчанию; конкретные guard-модули регистрируются в нём
# при импорте (см. guards/__init__.py). Контроллер по умолчанию резолвит отсюда.
DEFAULT = Registry()


def register(guard: Guard) -> Guard:
    return DEFAULT.register(guard)


def get(name: str) -> Guard:
    return DEFAULT.get(name)


def all_guards() -> dict[str, Guard]:
    return DEFAULT.all_guards()
