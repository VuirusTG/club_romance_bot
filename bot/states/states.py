from dataclasses import dataclass, field


@dataclass
class StateData:
    name: str
    data: dict = field(default_factory=dict)


class MemoryState:
    def __init__(self) -> None:
        self._states: dict[int, StateData] = {}

    def set(self, telegram_id: int, name: str, **data: object) -> None:
        self._states[telegram_id] = StateData(name=name, data=data)

    def get(self, telegram_id: int) -> StateData | None:
        return self._states.get(telegram_id)

    def clear(self, telegram_id: int) -> None:
        self._states.pop(telegram_id, None)


state_storage = MemoryState()

