from __future__ import annotations

import threading
import time
from collections.abc import Callable

from scry_core import boundary


def _take(lock: boundary.ServerLock, still: Callable[[], bool], got: list[bool]) -> None:
    took = lock.acquire_while(still)
    got.append(took)
    if took:
        lock.release()


def test_a_wait_for_the_lock_wakes_when_the_holder_releases_and_never_polls() -> None:
    """The waiter asks once at its start and once at the release, not repeatedly in between."""
    lock = boundary.ServerLock()
    asked: list[float] = []
    got: list[bool] = []

    def still() -> bool:
        asked.append(time.monotonic())
        return True

    with lock:
        waiter = threading.Thread(target=_take, args=(lock, still, got))
        waiter.start()
        time.sleep(0.5)
        assert waiter.is_alive() and len(asked) <= 2, len(asked)
    waiter.join(2)
    assert got == [True] and len(asked) <= 3, len(asked)


class _Asked:
    """A `due` that counts its askings."""

    def __init__(self) -> None:
        self.count = 0
        self.first = threading.Event()
        self.answer = True

    def __call__(self) -> bool:
        self.count += 1
        self.first.set()
        return self.answer


def test_a_wait_gives_up_at_the_release_that_finds_it_moot() -> None:
    lock = boundary.ServerLock()
    due = _Asked()
    got: list[bool] = []
    with lock:
        waiter = threading.Thread(target=_take, args=(lock, due, got))
        waiter.start()
        assert due.first.wait(2), "the waiter never asked"
        due.answer = False
    waiter.join(2)
    assert got == [False] and due.count == 2, (got, due.count)


def test_a_nested_hold_frees_the_lock_only_at_its_outermost_release() -> None:
    """An inner release neither frees the lock nor wakes the waiter: asked once, at its start."""
    lock = boundary.ServerLock()
    due = _Asked()
    got: list[bool] = []
    with lock:
        with lock:
            waiter = threading.Thread(target=_take, args=(lock, due, got))
            waiter.start()
            assert due.first.wait(2), "the waiter never asked"
        time.sleep(0.2)
        assert waiter.is_alive() and due.count == 1, due.count
    waiter.join(2)
    assert got == [True] and due.count == 2, due.count


def test_the_holder_is_known_and_a_wake_makes_a_waiter_ask_again_without_a_release() -> None:
    """A wake makes the waiter ask again while the lock is still held."""
    lock = boundary.ServerLock()
    due = _Asked()
    got: list[bool] = []
    seen: list[bool] = []
    with lock:
        assert lock.held_here()
        other = threading.Thread(target=lambda: seen.append(lock.held_here()))
        other.start()
        other.join(2)
        waiter = threading.Thread(target=_take, args=(lock, due, got))
        waiter.start()
        assert due.first.wait(2), "the waiter never asked"
        due.answer = False
        lock.wake()
        waiter.join(2)
        assert got == [False] and not waiter.is_alive(), got
    assert seen == [False]
