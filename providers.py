"""Project-level providers shim.

Wraps local-first-common's PROVIDERS and adds a "local" alias for OllamaProvider
so existing config files using `provider = "local"` continue to work.
"""
from local_first_common.providers import PROVIDERS as _PROVIDERS, OllamaProvider

# "local" is a legacy alias preserved for backward compatibility with config files
PROVIDERS = {**_PROVIDERS, "local": OllamaProvider}
