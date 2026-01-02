from __future__ import annotations

from urllib.parse import parse_qs, quote_plus, urlencode, urlparse, urlunparse


def make_search_url(store_url: str, query: str) -> str:
    if not store_url:
        raise ValueError("store_url is required")
    cleaned = store_url.strip()
    parsed = urlparse(cleaned)
    path = parsed.path or ""

    if "/recherche.aspx" in path:
        search_path = path
    elif path.endswith(".aspx"):
        search_path = f"{path[:-5]}/recherche.aspx"
    elif path.endswith("/"):
        search_path = f"{path}recherche.aspx"
    else:
        search_path = f"{path}/recherche.aspx"

    params = parse_qs(parsed.query, keep_blank_values=True)
    params["TexteRecherche"] = [query]
    query_string = urlencode(params, doseq=True, quote_via=quote_plus)

    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            search_path,
            parsed.params,
            query_string,
            parsed.fragment,
        )
    )
