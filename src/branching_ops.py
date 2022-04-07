from textwrap import dedent

from ops.charm import CharmBase as CharmBase_
import inspect


def load(parent: object, child: CharmBase_):
    # BEWARE: DON'T DO THIS AT HOME!
    #  THIS IS A DEMONSTRATION IMPLEMENTATION,
    #  WITH NO PRETENSE OF BEING GOOD CODE.
    #  PLEASE DON'T EVEN LOOK AT IT.
    for name, value in inspect.getmembers(parent):
        if not name.startswith('__'):
            try:
                setattr(child, name, value)
            except:
                pass


class Branch(CharmBase_):
    def __init__(self, parent, *args):
        # do not init CharmBase! the inheritance is just to mess with the type checker
        # we load the parent onto self, so that subclasses can use config, framework, the whole CharmBase package
        load(parent, self)
        self.__parent = parent
        pass

    # to confuse the type checker in a good way
    def branch(self, cls: 'Branch'): pass

    def config(self):
        return self.__parent.config


class CharmBase(CharmBase_):
    _branches = None

    def branch(self, type_: Branch):
        # to prevent any kind of gc'ing issue
        if not self._branches:
            self._branches = []
        branch = type_(self)  # noqa
        load(branch, self)
        self._branches.append(branch)


if __name__ == '__main__':
    from ops.testing import Harness

    class ConfiguredBranch(Branch):
        def __init__(self, *args):
            super().__init__(*args)
            # we can assume 'ka' to be there! how nice.
            self.ka = self.config['ka']


    class LeaderBranch(Branch):
        def __init__(self, *args):
            super().__init__(*args)
            self.bar = 'baz'

            if self.config.get('ka'):
                self.branch(ConfiguredBranch)


    class FollowerBranch(Branch):
        def __init__(self, *args):
            super().__init__(*args)
            self.foo = 'bar'


    class Root(CharmBase):
        def __init__(self, *args):
            super().__init__(*args)
            if self.unit.is_leader():
                self.branch(LeaderBranch)
            else:
                self.branch(FollowerBranch)


    config = dedent("""
    options:
      ka:
        description: |
          ching!
        type: string
    """)

    harness = Harness(Root, config=config)
    harness.begin()

    assert harness.charm.foo
    assert not getattr(harness.charm, 'bar', None)

    # leader
    harness = Harness(Root, config=config)
    harness.set_leader(True)
    harness.begin()

    assert harness.charm.bar
    assert not getattr(harness.charm, 'foo', None)
    assert not getattr(harness.charm, 'configured', None)

    # leader and configured
    harness = Harness(Root, config=config)
    harness.set_leader(True)
    harness.update_config({'ka': 'ching'})
    harness.begin()

    assert harness.charm.bar
    assert harness.charm.ka == 'ching'
