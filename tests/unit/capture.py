# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

from contextlib import contextmanager
from typing import Generic, Optional, Type, TypeVar

from ops.charm import CharmBase
from ops.framework import EventBase

_T = TypeVar("_T")


@contextmanager
def capture_events(charm: CharmBase, *types: Type[EventBase]):
    allowed_types = types or (EventBase,)

    captured = []
    _real_emit = charm.framework._emit

    def _wrapped_emit(evt):
        if isinstance(evt, allowed_types):
            captured.append(evt)
        return _real_emit(evt)

    charm.framework._emit = _wrapped_emit

    yield captured

    charm.framework._emit = _real_emit


class Captured(Generic[_T]):
    _event = None

    @property
    def event(self) -> Optional[_T]:
        return self._event

    @event.setter
    def event(self, val: _T):
        self._event = val


@contextmanager
def capture(charm: CharmBase, typ_: Type[_T] = EventBase) -> Captured[_T]:
    result = Captured()
    with capture_events(charm, typ_) as captured:
        if not captured:
            yield result

    assert len(captured) <= 1, f"too many events captured: {captured}"
    assert len(captured) >= 1, f"no event of type {typ_} emitted."
    event = captured[0]
    assert isinstance(event, typ_), f"expected {typ_}, not {type(event)}"
    result.event = event
