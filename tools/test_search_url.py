#!/usr/bin/env python3
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.leclerc_search import make_search_url as backend_make_search_url
from worker.leclerc_search import make_search_url as worker_make_search_url


def assert_equal(actual: str, expected: str) -> None:
    if actual != expected:
        raise AssertionError(f"Expected {expected}, got {actual}")


def run_tests(make_search_url):
    base = "https://fd6-courses.leclercdrive.fr/magasin-175901-175901-Seclin-Lorival"

    case_aspx = f"{base}.aspx"
    expected_aspx = (
        f"{base}/recherche.aspx?TexteRecherche=coca"
    )
    assert_equal(make_search_url(case_aspx, "coca"), expected_aspx)

    case_trailing = f"{base}/"
    expected_trailing = f"{base}/recherche.aspx?TexteRecherche=cafe"
    assert_equal(make_search_url(case_trailing, "cafe"), expected_trailing)

    case_existing = f"{base}/recherche.aspx?TexteRecherche=ancien&foo=bar"
    expected_existing = f"{base}/recherche.aspx?TexteRecherche=the&foo=bar"
    assert_equal(make_search_url(case_existing, "the"), expected_existing)


if __name__ == "__main__":
    run_tests(backend_make_search_url)
    run_tests(worker_make_search_url)
    print("OK")
