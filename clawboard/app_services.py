"""Legacy import facade; data and operating-system adapters have separate boundaries.

Assignments remain forwarded for existing diagnostic scripts that inject paths or
clipboard functions through this module. New code injects services directly.
"""
import sys
import types
from clawboard import data_adapter as _data, system as _system
from clawboard.data_adapter import DataMixin
from clawboard.system import SystemMixin

for _module in (_data, _system):
    for _name in dir(_module):
        if not _name.startswith('_'):
            globals().setdefault(_name, getattr(_module, _name))

class _CompatibilityModule(types.ModuleType):
    def __setattr__(self, name, value):
        for module in (_data, _system):
            if hasattr(module, name):
                setattr(module, name, value)
        super().__setattr__(name, value)

sys.modules[__name__].__class__ = _CompatibilityModule
