'''This is a library providing a utility for unittesting events fired on a
Harness-ed Charm.

Example usage:

>>> from charms.harness_extensions.v0.capture_events import capture
>>> with capture(RelationEvent) as captured:
>>>     harness.add_relation('foo', 'remote')
>>> assert captured.event.unit.name == 'remote'
'''

# The unique Charmhub library identifier, never change it
LIBID = "9fcdab70e26d4eee9797c0e542ab397a"

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 3

# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

from contextlib import contextmanager
from typing import Generic, Iterator, Optional, Type, TypeVar

from ops.charm import CharmBase
from ops.framework import EventBase

_T = TypeVar("_T", bound=EventBase)


@contextmanager
def capture_events(charm: CharmBase, *types: Type[EventBase]):
    """Capture all events of type `*types` (using instance checks)."""
    allowed_types = types or (EventBase,)

    captured = []
    _real_emit = charm.framework._emit

    def _wrapped_emit(evt):
        if isinstance(evt, allowed_types):
            captured.append(evt)
        return _real_emit(evt)

    charm.framework._emit = _wrapped_emit  # type: ignore # noqa # ugly

    yield captured

    charm.framework._emit = _real_emit  # type: ignore # noqa # ugly


class Captured(Generic[_T]):
    """Object to type and expose return value of capture()."""

    _event = None

    @property
    def event(self) -> Optional[_T]:
        """Return the captured event."""
        return self._event

    @event.setter
    def event(self, val: _T):
        self._event = val


@contextmanager
def capture(charm: CharmBase, typ_: Type[_T] = EventBase) -> Iterator[Captured[_T]]:
    """Capture exactly 1 event of type `typ_`.

    Will raise if more/less events have been fired, or if the returned event
    does not pass an instance check.
    """
    result = Captured()
    with capture_events(charm, typ_) as captured:
        if not captured:
            yield result

    assert len(captured) <= 1, f"too many events captured: {captured}"
    assert len(captured) >= 1, f"no event of type {typ_} emitted."
    event = captured[0]
    assert isinstance(event, typ_), f"expected {typ_}, not {type(event)}"
    result.event = event

