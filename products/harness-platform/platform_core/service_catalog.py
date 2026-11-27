"""Explicit server-owned catalogue for metered adapters.

The workshop starts with direct model/web/media adapters in their existing
Harness paths. It does not install marketplace research services. A future
adapter registers its own reviewed unit and receipt version at composition
time, then uses service_billing against the same wallet.
"""
import re
from types import MappingProxyType

_services = {}
SERVICES = MappingProxyType(_services)
MODEL_RATES = MappingProxyType({
    'deepseek-2026-11-18': 'DeepSeek',
    'openrouter-v1': 'OpenRouter',
    'deepseek-web-2026-11-27': 'DeepSeek',
    'deepseek-files-2026-11-25': 'DeepSeek',
})


def register(service, name, unit, version):
    """Trusted startup only. Never accept catalogue entries from a model or UI."""
    if not all(isinstance(value, str) and re.fullmatch(r'[a-z0-9][a-z0-9_.-]{1,79}', value)
               for value in (service, unit, version)):
        raise ValueError('Invalid metered service catalogue entry')
    if not isinstance(name, str) or not name.strip() or len(name) > 80:
        raise ValueError('Invalid service display name')
    entry = (name, unit, version)
    existing = _services.get(service)
    if existing is not None:
        if existing != entry:
            raise ValueError('A registered financial contract is immutable')
        return
    if version in MODEL_RATES or any(version == v or name == n for n, _, v in _services.values()):
        raise ValueError('Provider receipt version is already registered')
    _services[service] = entry
