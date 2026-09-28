from ..Config import Source
from .BaseSource import BaseSource, PageResult, SourceParseError
from .GooglePlay.GooglePlaySource import GooglePlaySource

_SOURCES: dict[Source, BaseSource] = {
    Source.GOOGLE_PLAY: GooglePlaySource(),
}


def get_source(source: Source | str) -> BaseSource:
    try:
        return _SOURCES[Source(source)]
    except (ValueError, KeyError):
        known = [s.value for s in _SOURCES]
        raise ValueError(f"Source {source!r} is not available. Available: {known}") from None


def all_sources() -> list[BaseSource]:
    return list(_SOURCES.values())


__all__ = ["BaseSource", "PageResult", "SourceParseError", "all_sources", "get_source"]
