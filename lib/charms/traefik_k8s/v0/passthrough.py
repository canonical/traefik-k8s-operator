"""Passthrough charm library.
"""
from typing import Iterable, Tuple

from ops import CharmBase, Object, Relation

# The unique Charmhub library identifier, never change it
LIBID = "b1f39dd94e594296b6be7d6c532d1774"

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 1


class Passthrough(Object):
    def __init__(self, charm: CharmBase, endpoint_in: str, endpoint_out: str, interface: str):
        super().__init__(charm, 'passthrough' + interface)
        self.charm = charm
        self.endpoint_in=endpoint_in
        self.endpoint_out=endpoint_out
        on_relation_in = charm.on[endpoint_in]
        on_relation_out = charm.on[endpoint_out]
        self.framework.observe(on_relation_in.relation_changed, self._on_relation_in_changed)
        self.framework.observe(on_relation_out.relation_changed, self._on_relation_out_changed)

    def _sort_relations(self, relations: Iterable[Relation]) -> Tuple[Relation]:
        return tuple(sorted(relations, key=lambda r:r.id))

    @property
    def relations_in(self):
        return self._sort_relations(self.charm.model.relations[self.endpoint_in])

    @property
    def relations_out(self):
        return self._sort_relations(self.charm.model.relations[self.endpoint_out])

    @property
    def relation_pairs(self):
        yield from zip(self.relations_in, self.relations_out)

    def map(self, relation: Relation):
        for r1,r2 in self.relation_pairs:
            if relation.name == self.endpoint_in:
                if r1 is relation:
                    return r2
            else:
                if r2 is relation:
                    return r1
    def _on_relation_in_changed(self, _):
        self._update()
    def _on_relation_out_changed(self, _):
        self._update()

    def copy(self, r_in: Relation, r_out: Relation):
        r_out.data[self.charm.app].clear()
        r_out.data[self.charm.app].update(r_in.data[r_in.app])

    def _update(self):
        for r_in, r_out in self.relation_pairs:
            self.copy(r_in, r_out)
            self.copy(r_out, r_in)
