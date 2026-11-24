from collections import defaultdict
from threading import Lock

_COUNTERS: dict[str, int] = defaultdict(int)
_LOCK = Lock()


def increment(name: str, amount: int = 1) -> int:
    with _LOCK:
        _COUNTERS[name] += amount
        return _COUNTERS[name]


def snapshot() -> dict[str, int]:
    with _LOCK:
        return dict(_COUNTERS)