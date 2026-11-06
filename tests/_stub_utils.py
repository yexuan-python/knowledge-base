from __future__ import annotations

import importlib.machinery
import importlib.util
import sys
import types


def _looks_like_real_module(module: types.ModuleType) -> bool:
    if getattr(module, "__file__", None):
        return True
    spec = getattr(module, "__spec__", None)
    return bool(spec is not None and getattr(spec, "origin", None))


def module_available(name: str) -> bool:
    current = sys.modules.get(name)
    if current is not None:
        if _looks_like_real_module(current):
            return True
        removed = sys.modules.pop(name, None)
        try:
            return importlib.util.find_spec(name) is not None
        except (ImportError, ValueError, AttributeError):
            return False
        finally:
            if removed is not None:
                sys.modules[name] = removed
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError, AttributeError):
        return False


def ensure_stub_module(name: str, *, is_package: bool = False) -> types.ModuleType | None:
    if module_available(name):
        return None

    module = sys.modules.get(name)
    if module is None or _looks_like_real_module(module):
        module = types.ModuleType(name)
        sys.modules[name] = module

    module.__spec__ = importlib.machinery.ModuleSpec(name, loader=None, is_package=is_package)
    if is_package:
        module.__path__ = []
    return module
