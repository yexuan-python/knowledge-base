from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


_MODULE_NAME = "knowledge_base.infrastructure._tianyancha_client_impl"
_MODULE_PATH = Path(__file__).with_name("integrations") / "tianyancha_client.py"
_SPEC = importlib.util.spec_from_file_location(_MODULE_NAME, _MODULE_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise ImportError(f"Unable to load Tianyancha client implementation from {_MODULE_PATH}")
_MODULE = sys.modules.get(_MODULE_NAME)
if _MODULE is None:
    _MODULE = importlib.util.module_from_spec(_SPEC)
    sys.modules[_MODULE_NAME] = _MODULE
    _SPEC.loader.exec_module(_MODULE)

TianyanchaClient = _MODULE.TianyanchaClient
TianyanchaCompanyProfile = _MODULE.TianyanchaCompanyProfile
TianyanchaManagementMember = _MODULE.TianyanchaManagementMember
requests = _MODULE.requests

__all__ = [
    "TianyanchaClient",
    "TianyanchaCompanyProfile",
    "TianyanchaManagementMember",
    "requests",
]
