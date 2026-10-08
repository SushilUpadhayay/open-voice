"""V1 Voice AI Pipeline package."""
import sys

_self = sys.modules[__name__]
sys.modules.setdefault("V1", _self)
sys.modules.setdefault("v1", _self)

