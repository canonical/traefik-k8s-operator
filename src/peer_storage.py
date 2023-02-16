import base64
import codecs
import collections
import marshal
import pickle
import typing
from typing import TYPE_CHECKING, Union, Any, Optional, Dict, Callable, List, Set, TypeVar, Hashable, Iterable

from ops.charm import CharmBase
from ops.framework import Object
from ops.model import RelationDataContent

if TYPE_CHECKING:
    from typing import Literal, Protocol


    class _Serializable(Protocol):
        handle_kind = ''

        @property
        def handle(self) -> 'Handle': ...  # noqa

        @handle.setter
        def handle(self, val: 'Handle'): ...  # noqa

        def snapshot(self) -> Dict[str, '_StorableType']: ...  # noqa

        def restore(self, snapshot: Dict[str, '_StorableType']) -> None: ...  # noqa


    class _StoredObject(Protocol):
        _under = None  # type: Any  # noqa


    # serialized data structure
    _SerializedData = Dict[str, 'JsonObject']

    _ObserverCallback = Callable[[Any], None]

    # types that can be stored natively
    _StorableType = Union[int, bool, float, str, bytes, Literal[None],
    List['_StorableType'],
    Dict[str, '_StorableType'],
    Set['_StorableType']]

    StoredObject = Union['StoredList', 'StoredSet', 'StoredDict']

_T = TypeVar("_T")

DEFAULT_ENDPOINT_NAME = "storage"
DEFAULT_RELATION_INTERFACE_NAME = "peer-storage"


class StorageNotReady(RuntimeError):
    """Raised if you attempt to use PeerStorage before the relation has been created."""


class PeerStorage:
    """Stored state data bound to a specific Object, backed by a peer relation."""

    if TYPE_CHECKING:
        # to help the type checker and IDEs:
        @property
        def _parent(self) -> Object:  # noqa
            pass  # pyright: reportGeneralTypeIssues=false

        @property  # noqa
        def _endpoint(self) -> str:  # noqa
            pass  # pyright: reportGeneralTypeIssues=false

        @property  # noqa
        def _peer_relation_data(self) -> Optional[RelationDataContent]:  # noqa
            pass  # pyright: reportGeneralTypeIssues=false

    def __init__(self, owner: CharmBase,
                 endpoint: str = DEFAULT_ENDPOINT_NAME,
                 interface: str = DEFAULT_RELATION_INTERFACE_NAME):
        # check that relation meta has the specified endpoint
        relation_meta = owner.meta.peers.get(endpoint)
        if not relation_meta or not relation_meta.interface_name == interface:
            raise ValueError(f'Charm metadata does not include '
                             f'`peers: [{endpoint}: [interface: {interface}]]')

        rel = owner.model.get_relation(endpoint)
        data = rel.data[owner.unit] if rel else None

        # __dict__ is used to avoid infinite recursion.
        self.__dict__["_peer_relation_data"] = data

    @property
    def is_ready(self):
        return self._peer_relation_data is not None

    def _check_ready(self):
        if not self.is_ready:
            raise StorageNotReady()

    def __getattr__(self, key: str) -> Union['_StorableType', 'StoredObject']:
        # "on" is the only reserved key that can't be used in the data map.
        if key not in self._peer_relation_data:
            raise AttributeError(f"attribute '{key}' is not stored")
        return _decode(self._peer_relation_data[key])

    def __setattr__(self, key: str, value: Union['_StorableType', '_StoredObject']):
        if key == '_peer_relation_data':
            raise RuntimeError(f'cannot set protected attribute: PeerStorage().{key}')

        self._check_ready()

        try:
            marshal.dumps(value)
        except ValueError as e:
            raise RuntimeError(f'cannot set to values of type {type(value)}; '
                               f'needs to be a simple type.') from e
        self._peer_relation_data[key] = _encode(value)


    def set_default(self, fail_if_not_ready=False, **kwargs: '_StorableType'):
        """Set the value of any given key if it has not already been set."""
        if not fail_if_not_ready and not self.is_ready:
            return
        self._check_ready()

        for k, v in kwargs.items():
            if k not in self._peer_relation_data:
                self._peer_relation_data[k] = _encode(v)


def _encode(value: Any) -> str:
    return codecs.encode(pickle.dumps(value), "base64").decode()


def _decode(value:str) -> Any:
    data = pickle.loads(codecs.decode(value.encode(), "base64"))
    return data
