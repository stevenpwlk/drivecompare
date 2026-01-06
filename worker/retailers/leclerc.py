# worker/retailers/leclerc.py
from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import quote_plus, urlparse

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, sync_playwright

LOG_DIR = Path(os.getenv("LOG_DIR", "/logs"))
DEFAULT_TIMEOUT_MS = int(os.getenv("LECLERC_TIMEOUT_MS", "15000"))

# CDP: ton worker se connecte au Chromium (leclerc-gui) via CDP (souvent proxy 9223)
LECLERC_CDP_URL = os.getenv("LECLERC_CDP_URL", "http://127.0.0.1:9222")

LECLERC_BACKEND_URL = os.getenv("LECLERC_BACKEND_URL", "http://backend:8000")

# URL "à ouvrir" côté user quand il faut valider à la main
LECLERC_UNBLOCK_URL = os.getenv("LECLERC_UNBLOCK_URL", "http://127.0.0.1:5800")

UNBLOCK_POLL_INTERVAL = int(os.getenv("UNBLOCK_POLL_INTERVAL", "3"))
UNBLOCK_TIMEOUT = int(os.getenv("UNBLOCK_TIMEOUT", "900"))

MAX_BLOCK_RETRIES = int(os.getenv("MAX_BLOCK_RETRIES", "2"))

LECLERC_STORE_URL = os.getenv(
    "LECLERC_STORE_URL",
    "https://fd6-courses.leclercdrive.fr/magasin-175901-175901-seclin-lorival.aspx",
)
LECLERC_STORE_LABEL = os.getenv("LECLERC_STORE_LABEL", "Leclerc")


class CaptchaRequired(RuntimeError):
    def __init__(
        self,
        *,
        stage: str,
        blocked_url: str | None,
        unblock_url: str | None = None,
        artifacts: dict[str, str] | None = None,
    ) -> None:
        super().__init__("captcha_required")
        self.stage = stage
        self.blocked_url = blocked_url
        self.unblock_url = unblock_url or LECLERC_UNBLOCK_URL
        self.artifacts = artifacts or {}


class SharedLeclercBrowser:
    """
    Connexion CDP à un Chromium persistant (leclerc-gui).
    IMPORTANT: on garde une page "worker" dédiée (about:blank#drivecompare_worker)
    pour éviter de naviguer sur un onglet que tu es en train d'utiliser dans le VNC.
    """

    def __init__(self, cdp_url: str = LECLERC_CDP_URL) -> None:
        self.cdp_url = cdp_url
        self._playwright = None
        self._browser = None
        self._context = None
        self._worker_page: Page | None = None
        self.logger = logging.getLogger(__name__)

    def _ensure_playwright(self):
        if self._playwright is None:
            self._playwright = sync_playwright().start()
        return self._playwright

    def _connect_over_cdp(self):
        last_error = None
        for attempt in range(1, 31):
            try:
                playwright = self._ensure_playwright()
                return playwright.chromium.connect_over_cdp(self.cdp_url)
            except Exception as exc:
                last_error = exc
                self.logger.warning(
                    "CDP connect attempt %s/30 failed (%s). Retrying...",
                    attempt,
                    exc,
                )
                time.sleep(2)
        raise last_error

    def _ensure_browser(self):
        if self._browser and self._browser.is_connected():
            return self._browser
        self._browser = self._connect_over_cdp()
        self._context = None
        self._worker_page = None
        return self._browser

    def _ensure_context(self):
        browser = self._ensure_browser()
        # sur un chromium persistant, il y a souvent déjà 1 context
        if self._context:
            return self._context
        self._context = browser.contexts[0] if browser.contexts else browser.new_context()
        return self._context

    def ensure_worker_page(self) -> Page:
        context = self._ensure_context()

        if self._worker_page and not self._worker_page.is_closed():
            return self._worker_page

        # crée une page dédiée worker
        page = context.new_page()
        try:
            page.goto("about:blank#drivecompare_worker", wait_until="domcontentloaded", timeout=3000)
        except Exception:
            pass
        self._worker_page = page
        return page


_shared_browser = SharedLeclercBrowser()


def ensure_page() -> Page:
    return _shared_browser.ensure_worker_page()


@dataclass
class SearchResult:
    items: list[dict[str, Any]]
    debug: dict[str, Any]


class LeclercRetailer:
    def __init__(
        self,
        page: Page,
        job_id: int,
        *,
        on_block: Callable[[str, str | None], None] | None = None,
        on_resume: Callable[[], None] | None = None,
    ) -> None:
        self.page = page
        self.job_id = job_id
        self.on_block = on_block
        self.on_resume = on_resume
        self.logger = logging.getLogger(__name__)

        self.log_dir = LOG_DIR / "leclerc" / str(job_id)

        self._network_entries: list[dict[str, Any]] = []
        self._network_handlers: dict[str, Any] = {}

        # XHR JSON capturés (fallback parsing)
        self._xhr_json: list[dict[str, Any]] = []

    def _timestamp(self) -> int:
        return int(time.time())

    def _ensure_dirs(self) -> None:
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def _start_network_capture(self) -> None:
        self._network_entries = []
        self._xhr_json = []

        def on_response(response) -> None:
            try:
                request = response.request
                entry = {
                    "url": response.url,
                    "status": response.status,
                    "method": request.method,
                    "resource_type": request.resource_type,
                    "ok": response.ok,
                }
                self._network_entries.append(entry)

                # Capture JSON XHR/fetch (utile si DOM parsing = 0 items)
                if request.resource_type in ("xhr", "fetch"):
                    ct = (response.headers.get("content-type") or "").lower()
                    if "application/json" in ct:
                        # éviter de parser des payloads gigantesques
                        cl = response.headers.get("content-length")
                        if cl and cl.isdigit() and int(cl) > 2_500_000:
                            return
                        try:
                            data = response.json()
                            self._xhr_json.append({"url": response.url, "data": data})
                        except Exception:
                            pass
            except Exception:
                self.logger.debug("Failed to capture response", exc_info=True)

        def on_request_failed(request) -> None:
            try:
                self._network_entries.append(
                    {
                        "url": request.url,
                        "status": None,
                        "method": request.method,
                        "resource_type": request.resource_type,
                        "ok": False,
                        "failure": request.failure,
                    }
                )
            except Exception:
                self.logger.debug("Failed to capture request failure", exc_info=True)

        self.page.on("response", on_response)
        self.page.on("requestfailed", on_request_failed)
        self._network_handlers = {"response": on_response, "requestfailed": on_request_failed}

    def _stop_network_capture(self) -> None:
        if not self._network_handlers:
            return
        for event, handler in self._network_handlers.items():
            try:
                self.page.off(event, handler)
            except Exception:
                self.logger.debug("Failed to detach network handler", exc_info=True)
        self._network_handlers = {}

    def _build_network_summary(self) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "total_entries": len(self._network_entries),
            "by_status": {},
            "by_resource": {},
            "entries": self._network_entries[-200:],
        }
        for entry in self._network_entries:
            status = entry.get("status")
            resource = entry.get("resource_type")
            summary["by_status"][str(status)] = summary["by_status"].get(str(status), 0) + 1
            summary["by_resource"][str(resource)] = summary["by_resource"].get(str(resource), 0) + 1
        return summary

    def _capture_artifacts(self, label: str) -> dict[str, str]:
        self._ensure_dirs()
        stamp = self._timestamp()
        screenshot_path = self.log_dir / f"leclerc_{label}_{stamp}.png"
        html_path = self.log_dir / f"leclerc_{label}_{stamp}.html"
        network_path = self.log_dir / f"leclerc_{label}_{stamp}_network.json"

        try:
            self.page.screenshot(path=str(screenshot_path), full_page=True)
        except Exception:
            self.logger.exception("Failed to capture screenshot")

        try:
            html_path.write_text(self.page.content(), encoding="utf-8")
        except Exception:
            self.logger.exception("Failed to capture HTML")

        try:
            network_path.write_text(
                json.dumps(self._build_network_summary(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            self.logger.exception("Failed to capture network summary")

        payload = {"screenshot": str(screenshot_path), "html": str(html_path), "network": str(network_path)}
        try:
            payload["url"] = self.page.url
        except Exception:
            payload["url"] = None
        return payload

    def capture_artifacts(self, label: str) -> dict[str, str]:
        return self._capture_artifacts(label)

    def _handle_cookie_banner(self) -> None:
        buttons = [
            "button:has-text('Tout accepter')",
            "button:has-text('Accepter')",
            "button:has-text(\"J'accepte\")",
        ]
        for selector in buttons:
            try:
                button = self.page.locator(selector).first
                if button.count() and button.is_visible(timeout=1500):
                    button.click(timeout=1500)
                    self.page.wait_for_timeout(500)
                    return
            except PlaywrightTimeoutError:
                continue
            except Exception:
                self.logger.debug("Cookie accept failed", exc_info=True)

    # --- Détection challenge / blocage (évite les faux positifs "datadome" sur pages normales) ---

    def _is_challenge_page(self, html: str, url: str | None, title: str | None) -> bool:
        low = (html or "").lower()
        u = (url or "").lower()
        t = (title or "").lower()

        # Signaux forts DataDome (page challenge réelle)
        if "captcha-delivery" in low or "captcha-delivery" in u:
            return True
        if "geo.captcha" in low or "geo.captcha" in u:
            return True
        if "dd_captcha" in low or "datadome-captcha" in low:
            return True

        # Cloudflare / interstitiels classiques
        if "checking your browser" in low:
            return True
        if "verify you are human" in low or "verify you are a human" in low:
            return True

        # Messages explicites
        if "access denied" in low or "accès refusé" in low:
            return True
        if "trafic inhabituel" in low or "unusual traffic" in low:
            return True

        # IMPORTANT:
        # La présence de "datadome" dans le HTML n'est PAS un blocage (souvent taggué sur pages normales)
        # La présence de hCaptcha/recaptcha peut arriver sur login → on ne le considère pas "bloqué" ici.
        # (Le login gère ses propres étapes et peut remonter captcha_required si hcaptcha/2fa.)
        _ = t  # juste pour éviter lint dans certains environnements
        return False

    def _raise_if_challenge(self, stage: str) -> None:
        try:
            html = self.page.content()
        except Exception:
            html = ""
        try:
            url = self.page.url
        except Exception:
            url = None
        try:
            title = self.page.title()
        except Exception:
            title = None

        if self._is_challenge_page(html, url, title):
            artifacts = self._capture_artifacts(f"blocked_{stage}")
            raise CaptchaRequired(stage=stage, blocked_url=url, unblock_url=LECLERC_UNBLOCK_URL, artifacts=artifacts)

    def _wait_quiet(self) -> None:
        try:
            self.page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            self.page.wait_for_timeout(1200)

    def _build_search_url(self, query: str) -> str:
        base = LECLERC_STORE_URL
        if base.endswith(".aspx"):
            base = base[: -len(".aspx")]
        base = base.rstrip("/")
        return f"{base}/recherche.aspx?TexteRecherche={quote_plus(query)}"

    # --- Parsing DOM (best-effort) ---

    def _extract_price(self, text: str) -> tuple[str | None, float | None]:
        m = re.search(r"(\d+[,.]\d{2})\s*€", text)
        if not m:
            return None, None
        price_text = m.group(1).replace(",", ".")
        try:
            return price_text, float(price_text)
        except ValueError:
            return price_text, None

    def _extract_unit_price(self, text: str) -> str | None:
        # Ex: "1,64 € / l" ou "10,33 € / kg"
        m = re.search(r"(\d+[,.]\d{2})\s*€\s*/\s*([a-zA-Z]+)", text)
        if not m:
            return None
        return f"{m.group(1).replace(',', '.')} €/ {m.group(2)}"

    def _parse_product_card_dom(self, card, base_url: str) -> dict[str, Any] | None:
        try:
            raw_text = card.inner_text()
        except Exception:
            raw_text = ""

        price_text, price_value = self._extract_price(raw_text)
        if not price_text:
            return None

        unit_price = self._extract_unit_price(raw_text)

        title = None
        try:
            title_locator = card.locator(
                "h3, h2, .product-title, .product__title, [data-testid*='title'], [data-testid*='name'], a[title]"
            ).first
            if title_locator.count():
                title = title_locator.inner_text().strip()
        except Exception:
            title = None

        if not title:
            # fallback: première ligne "non vide"
            lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
            if lines:
                title = lines[0][:160]

        url = None
        try:
            href = card.locator("a").first.get_attribute("href")
            if href:
                url = href if href.startswith("http") else f"{base_url}{href}"
        except Exception:
            url = None

        return {
            "name": title,
            "price": price_value if price_value is not None else price_text,
            "unit_price": unit_price,
            "url": url,
            "store": LECLERC_STORE_LABEL,
        }

    def _parse_search_results_dom(self, limit: int, base_url: str) -> list[dict[str, Any]]:
        # sélecteurs très permissifs + heuristique "contient prix"
        selectors = [
            "article",
            "div",
            "li",
        ]
        locator = self.page.locator(",".join(selectors))

        items: list[dict[str, Any]] = []
        count = locator.count()

        # On évite d’itérer sur 20 000 div : on borne
        max_scan = min(count, 4000)

        for index in range(max_scan):
            card = locator.nth(index)
            try:
                # micro-filtre : si le texte ne contient pas "€", skip
                txt = card.inner_text(timeout=300)
                if "€" not in txt:
                    continue
            except Exception:
                continue

            item = self._parse_product_card_dom(card, base_url)
            if item:
                items.append(item)
                if len(items) >= limit:
                    break

        # petite dédup par (name, price)
        dedup: list[dict[str, Any]] = []
        seen = set()
        for it in items:
            k = (it.get("name"), it.get("price"))
            if k in seen:
                continue
            seen.add(k)
            dedup.append(it)

        return dedup[:limit]

    # --- Parsing XHR JSON (fallback) ---

    def _iter_lists(self, obj: Any) -> Iterable[list[Any]]:
        if isinstance(obj, list):
            yield obj
            for v in obj:
                yield from self._iter_lists(v)
        elif isinstance(obj, dict):
            for v in obj.values():
                yield from self._iter_lists(v)

    def _score_candidate_list(self, lst: list[Any]) -> int:
        if not lst or not isinstance(lst[0], dict):
            return 0
        sample = lst[0]
        keys = {str(k).lower() for k in sample.keys()}
        score = 0
        for k in keys:
            if "prix" in k or "price" in k:
                score += 3
            if "libell" in k or "name" in k or "label" in k or "designation" in k or "title" in k:
                score += 2
            if "url" in k or "slug" in k:
                score += 1
        # favorise les listes longues
        return score * min(len(lst), 200)

    def _extract_first(self, d: dict[str, Any], wanted: list[str]) -> Any:
        low_map = {str(k).lower(): k for k in d.keys()}
        for w in wanted:
            k = low_map.get(w.lower())
            if k is not None:
                return d.get(k)
        return None

    def _extract_items_from_xhr(self, limit: int) -> list[dict[str, Any]]:
        best: list[dict[str, Any]] = []

        # On parcourt les JSON capturés et on cherche la "meilleure" liste de produits
        candidates: list[list[Any]] = []
        for payload in self._xhr_json:
            data = payload.get("data")
            for lst in self._iter_lists(data):
                if lst and isinstance(lst[0], dict):
                    candidates.append(lst)

        # choisir la meilleure liste
        best_lst: list[Any] | None = None
        best_score = 0
        for lst in candidates:
            s = self._score_candidate_list(lst)
            if s > best_score:
                best_score = s
                best_lst = lst

        if not best_lst:
            return best

        parsed = urlparse(LECLERC_STORE_URL)
        base_url = f"{parsed.scheme}://{parsed.netloc}" if parsed.netloc else LECLERC_STORE_URL

        for prod in best_lst[: max(limit, 60)]:
            if not isinstance(prod, dict):
                continue

            name = self._extract_first(
                prod,
                ["libelle", "libellé", "label", "name", "designation", "titre", "title", "nom"],
            )
            if isinstance(name, dict):
                # parfois name={value:"..."}
                name = name.get("value") if "value" in name else None
            if isinstance(name, list):
                name = name[0] if name else None
            name = str(name).strip() if name else None

            price = self._extract_first(
                prod,
                ["prix", "prixttc", "price", "pricevalue", "montant", "amount"],
            )

            unit_price = self._extract_first(
                prod,
                ["prixunitaire", "unitprice", "prix_unitaire", "unit_price"],
            )

            url = self._extract_first(prod, ["url", "href", "link"])
            if url and isinstance(url, str) and not url.startswith("http"):
                url = f"{base_url}{url}"

            if not name or price is None:
                continue

            best.append(
                {
                    "name": name[:200],
                    "price": price,
                    "unit_price": unit_price,
                    "url": url,
                    "store": LECLERC_STORE_LABEL,
                }
            )
            if len(best) >= limit:
                break

        return best

    # --- API publique ---

    def login(
        self,
        *,
        email: str,
        password: str,
        auth_url: str,
        verify_url: str | None = None,
        save_storage_state: bool = True,
    ) -> dict[str, Any]:
        """
        Login best-effort.
        - Si hCaptcha / 2FA détecté => CaptchaRequired(stage=...) pour validation manuelle via UI.
        - Ne tente PAS de bypass captcha.
        """
        self.page.set_default_timeout(DEFAULT_TIMEOUT_MS)
        self._start_network_capture()
        try:
            self.page.goto(auth_url, wait_until="domcontentloaded", timeout=DEFAULT_TIMEOUT_MS)
            self._handle_cookie_banner()
            self._wait_quiet()

            self._raise_if_challenge("login_entry")

            def _fill_first(selectors: list[str], value: str) -> bool:
                for sel in selectors:
                    try:
                        loc = self.page.locator(sel).first
                        if loc.count() and loc.is_visible():
                            loc.click(timeout=2000)
                            loc.fill(value, timeout=5000)
                            return True
                    except Exception:
                        continue
                return False

            # étape email (parfois 2-step)
            _fill_first(
                [
                    "input[type='email']",
                    "input[name*='mail' i]",
                    "input[id*='mail' i]",
                    "input[name*='login' i]",
                    "input[id*='login' i]",
                ],
                email,
            )
            self.page.wait_for_timeout(200)

            # bouton continuer éventuel
            for sel in [
                "button:has-text('Continuer')",
                "button:has-text('Suivant')",
                "button[type='submit']",
            ]:
                try:
                    btn = self.page.locator(sel).first
                    if btn.count() and btn.is_visible():
                        btn.click(timeout=3000)
                        break
                except Exception:
                    pass

            # attendre password si besoin
            try:
                self.page.locator("input[type='password']").first.wait_for(timeout=DEFAULT_TIMEOUT_MS)
            except Exception:
                # peut être déjà là, ou page spéciale
                pass

            # si hcaptcha / recaptcha présents -> validation manuelle
            try:
                html = self.page.content().lower()
                if "hcaptcha" in html or "recaptcha" in html:
                    artifacts = self._capture_artifacts("blocked_login_hcaptcha")
                    raise CaptchaRequired(
                        stage="login_hcaptcha",
                        blocked_url=self.page.url,
                        unblock_url=LECLERC_UNBLOCK_URL,
                        artifacts=artifacts,
                    )
            except CaptchaRequired:
                raise
            except Exception:
                pass

            pwd_ok = _fill_first(
                ["input[type='password']", "input[name*='pass' i]", "input[id*='pass' i]"],
                password,
            )
            if not pwd_ok:
                artifacts = self._capture_artifacts("login_missing_password")
                return {"ok": False, "error": "password_field_not_found", "url": self.page.url, "artifacts": artifacts}

            self.page.wait_for_timeout(200)

            # submit
            submitted = False
            for sel in [
                "button:has-text('Me connecter')",
                "button:has-text('Se connecter')",
                "button[type='submit']",
                "input[type='submit']",
            ]:
                try:
                    loc = self.page.locator(sel).first
                    if loc.count() and loc.is_visible():
                        loc.click(timeout=5000)
                        submitted = True
                        break
                except Exception:
                    continue

            if not submitted:
                artifacts = self._capture_artifacts("login_no_submit")
                return {"ok": False, "error": "submit_not_found", "url": self.page.url, "artifacts": artifacts}

            self._wait_quiet()

            # 2FA (code 6 chiffres) => manuel
            try:
                low = self.page.content().lower()
                if "6" in low and "chiffre" in low and "code" in low:
                    artifacts = self._capture_artifacts("blocked_login_2fa")
                    raise CaptchaRequired(
                        stage="login_2fa",
                        blocked_url=self.page.url,
                        unblock_url=LECLERC_UNBLOCK_URL,
                        artifacts=artifacts,
                    )
            except CaptchaRequired:
                raise
            except Exception:
                pass

            logged_in = True
            if verify_url:
                try:
                    self.page.goto(verify_url, wait_until="domcontentloaded", timeout=DEFAULT_TIMEOUT_MS)
                    self._handle_cookie_banner()
                    self._wait_quiet()
                    if "authentification.aspx" in self.page.url.lower():
                        logged_in = False
                except Exception:
                    logged_in = False
            else:
                if "authentification.aspx" in self.page.url.lower():
                    logged_in = False

            if save_storage_state:
                try:
                    state_path = "/sessions/leclerc/storage_state.json"
                    os.makedirs(os.path.dirname(state_path), exist_ok=True)
                    self.page.context.storage_state(path=state_path)
                except Exception:
                    pass

            return {"ok": True, "logged_in": logged_in, "url": self.page.url, "title": self.page.title()}
        finally:
            self._stop_network_capture()

    def search(self, query: str, limit: int = 20) -> SearchResult:
        self._ensure_dirs()
        self.page.set_default_timeout(DEFAULT_TIMEOUT_MS)

        start = time.monotonic()
        block_attempts = 0

        self._start_network_capture()
        try:
            # 1) store home
            self.page.goto(LECLERC_STORE_URL, wait_until="domcontentloaded", timeout=DEFAULT_TIMEOUT_MS)
            self._handle_cookie_banner()
            self._wait_quiet()
            self._raise_if_challenge("store_home")

            # 2) search
            search_url = self._build_search_url(query)
            self.page.goto(search_url, wait_until="domcontentloaded", timeout=DEFAULT_TIMEOUT_MS)
            self._handle_cookie_banner()
            self._wait_quiet()
            self._raise_if_challenge("search")

            # parsing
            parsed = urlparse(LECLERC_STORE_URL)
            base_url = f"{parsed.scheme}://{parsed.netloc}" if parsed.netloc else LECLERC_STORE_URL

            items = self._parse_search_results_dom(limit, base_url)

            # fallback XHR JSON
            if not items:
                items = self._extract_items_from_xhr(limit)

            # retry blocage si jamais
            if not items and block_attempts < MAX_BLOCK_RETRIES:
                block_attempts += 1

            debug: dict[str, Any] = {
                "final_url": self.page.url,
                "page_title": None,
                "timing_ms": int((time.monotonic() - start) * 1000),
            }
            try:
                debug["page_title"] = self.page.title()
            except Exception:
                debug["page_title"] = None

            if not items:
                debug.update(self._capture_artifacts("noresults"))

            return SearchResult(items=items, debug=debug)

        except CaptchaRequired:
            raise
        except Exception:
            self._capture_artifacts("error")
            self.logger.exception("Leclerc search failed")
            raise
        finally:
            self._stop_network_capture()


__all__ = ["LeclercRetailer", "ensure_page", "SearchResult", "CaptchaRequired"]
