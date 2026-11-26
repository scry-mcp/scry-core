"""The shared dictionaries of rows, held to the contract a server's base meets."""

from __future__ import annotations

from collections.abc import Iterable

import pytest

from scry_core import conformance
from scry_core.knowledge import Scope, Support, sealed, shared
from scry_core.knowledge import base as rows_base


class Shared:
    """A server's view of the shared base."""

    def __init__(self, scopes: tuple[Scope, ...]) -> None:
        self.scopes = scopes

    def support(self) -> Support:
        return Support(scopes=self.scopes, chips=shared.CHIPS)

    def rows_base(self, fts5: bool | None = None) -> rows_base.Base:
        return rows_base.Base.load(*self.rows_sources(), lock=shared.rows_lock(), fts5=fts5)

    def rows_sources(self) -> tuple[str, ...]:
        return ("scry_core",)

    def rows_lock(self) -> sealed.Lock:
        return shared.rows_lock()

    def code_scopes(self) -> Iterable[str]:
        return ()


class TestAsAPcServerLoadsIt(conformance.KnowledgeContract):
    """DOSBox-X: the chips, no cpu."""

    @pytest.fixture
    def subject(self) -> Shared:
        return Shared((Scope("ibm-pc"),))


class TestAsScryMameLoadsIt(conformance.KnowledgeContract):
    """MAME: the chips and cpus."""

    @pytest.fixture
    def subject(self) -> Shared:
        return Shared(shared.CPUS)

