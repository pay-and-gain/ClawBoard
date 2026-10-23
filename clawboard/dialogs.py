"""Compatibility facade for independently maintained Tk dialog adapters.

Legacy diagnostics patch this module's paths/functions. Forward assignments to
the adapter that uses a symbol so an old injection keeps its original effect.
"""
import sys
import types
from clawboard import settings_dialog as _settings
from clawboard import transform_dialog as _transform
from clawboard import export_dialog as _export
from clawboard import exports as _exports
from clawboard.settings_dialog import SettingsWindow
from clawboard.transform_dialog import TransformWindow
from clawboard.export_dialog import ExportDialog

_MODULES = (_settings, _transform, _export, _exports)
_FORWARDED = {}
for _module in _MODULES:
    for _name in dir(_module):
        if not _name.startswith('_') and _name not in ('SettingsWindow', 'TransformWindow', 'ExportDialog'):
            _FORWARDED.setdefault(_name, []).append(_module)
            # Keep a local attribute too: unittest.mock.patch uses __dict__ to
            # decide whether to restore with setattr or delattr on exit.
            globals().setdefault(_name, getattr(_module, _name))


class _CompatibilityModule(types.ModuleType):
    def __getattr__(self, name):
        targets = _FORWARDED.get(name)
        if targets:
            return getattr(targets[0], name)
        raise AttributeError(name)

    def __setattr__(self, name, value):
        targets = _FORWARDED.get(name)
        if targets:
            for module in targets:
                setattr(module, name, value)
        super().__setattr__(name, value)


sys.modules[__name__].__class__ = _CompatibilityModule
