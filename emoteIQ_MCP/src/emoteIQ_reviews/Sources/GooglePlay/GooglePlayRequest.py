import json
from typing import Optional, NamedTuple
from urllib.parse import urlencode

from .GooglePlayFilters import GooglePlayFilters, GooglePlaySort

RPC_ID = "oCPfdb"

SORT_CODES = {
    GooglePlaySort.HELPFULNESS: 1,
    GooglePlaySort.NEWEST: 2,
    GooglePlaySort.RATING: 3,
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://play.google.com",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Dest": "empty",
    "sec-ch-ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
}

class GooglePlayRequest(NamedTuple):
    url: str
    body: str
  
def build_filter_slot(filters: GooglePlayFilters) -> list:
    slot = [None] * 8 + [2]
    slot[1] = filters.stars
    slot[6] = int(filters.sentiment) if filters.sentiment else None
    return slot
  
def build_request(
    base_url: str, filters: GooglePlayFilters, 
    count: int, token: Optional[str] = None
) -> GooglePlayRequest:
    
    query = urlencode({"hl": filters.lang, "gl": filters.country})
    url = f"{base_url}/_/PlayStoreUi/data/batchexecute?{query}"
    paging = [count, None, token] if token else [count]
    inner = [
        None,
        [2, SORT_CODES[filters.sort], paging, None, build_filter_slot(filters)],
        [filters.app_id, 7],
    ]

    outer = [[[RPC_ID, json.dumps(inner, separators=(",", ":")), None, "generic"]]]
    body = urlencode({"f.req": json.dumps(outer, separators=(",", ":"))})
    
    return GooglePlayRequest(url=url, body=body)
    
