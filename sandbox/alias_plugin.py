"""pytest plugin (loaded with -p alias_plugin): import the module under test under its repo path.

Upstream test files import the module by its path in its own repo (e.g. `gui.inline_markdown`);
the scorer keeps it, unedited, at /work/src/<name>.py, where mutants are applied. $SUITE_ALIASES
names a JSON object {repo dotted name: flat module name}. A meta-path finder resolves each
dotted name, when it is first imported, to the flat module object itself (one module object, so
attribute patching and identity checks behave as in the repo), and its parent packages to empty
stub packages. Nothing is imported until the test file asks for it, so a mutant that raises at
import time still fails at collection. Inert when $SUITE_ALIASES is unset.
"""
import importlib
import importlib.abc
import importlib.machinery
import json
import os
import sys


class _AliasLoader(importlib.abc.Loader):
    def __init__(self, target):
        self.target = target

    def create_module(self, spec):
        if self.target is None:
            return None            # stub package: default module creation
        self.module = importlib.import_module(self.target)
        self.own_spec = self.module.__spec__
        return self.module

    def exec_module(self, module):
        if self.target is not None:
            module.__spec__ = self.own_spec   # importlib overwrote it with the alias spec


class _AliasFinder(importlib.abc.MetaPathFinder):
    def __init__(self, aliases):
        self.aliases = aliases
        self.parents = {".".join(k.split(".")[:i]) for k in aliases for i in range(1, k.count(".") + 1)}

    def find_spec(self, fullname, path=None, target=None):
        if fullname in self.aliases:
            return importlib.machinery.ModuleSpec(fullname, _AliasLoader(self.aliases[fullname]))
        if fullname in self.parents:
            spec = importlib.machinery.ModuleSpec(fullname, _AliasLoader(None), is_package=True)
            spec.submodule_search_locations = []
            return spec
        return None


_path = os.environ.get("SUITE_ALIASES")
if _path:
    with open(_path) as f:
        sys.meta_path.insert(0, _AliasFinder(json.load(f)))
