from .BaseConfig import AppConfig, SourceConfig
from .GooglePlayConfig import GooglePlayConfig
from .Source import Source


app_config = AppConfig()

_SOURCE_CONFIGS: dict[Source, SourceConfig] = {
    Source.GOOGLE_PLAY: GooglePlayConfig(),
}


def get_source_config(source: Source | str) -> SourceConfig:
    try:
        return _SOURCE_CONFIGS[Source(source)]
    except (ValueError, KeyError):
        known = [s.value for s in _SOURCE_CONFIGS]
        raise ValueError(
            f"No configuration found for source {source!r}. Configured: {known}"
        ) from None


__all__ = [
    "Source",
    "SourceConfig",
    "app_config",
    "get_source_config",
]