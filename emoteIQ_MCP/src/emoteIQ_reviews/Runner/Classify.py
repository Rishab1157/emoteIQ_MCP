from enum import StrEnum

from ..Sources import PageResult


class Outcome(StrEnum):
    OK = "ok"
    END = "end"
    EMPTY = "empty"
    HTTP_ERROR = "http_error"
    NETWORK_ERROR = "network_error"
    PARSE_ERROR = "parse_error"



def classify(page: PageResult) -> Outcome:
    if page.status_code != 200:
        return Outcome.HTTP_ERROR
    if page.reviews:
        return Outcome.OK if page.next_token else Outcome.END
    return Outcome.EMPTY
