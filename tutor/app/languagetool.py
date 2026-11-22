"""Adapter lokalnego serwera LanguageTool (07 §4.2). Opcjonalny, wyłączony domyślnie, tylko localhost.

Bezpieczeństwo: host ∈ {127.0.0.1, localhost, ::1}, schemat http(s), bez danych logowania w URL; przekierowania
HTTP wyłączone (serwer na localhost nie może odesłać tekstu ucznia na obcy host); `trust_env=False` (zmienne
HTTP_PROXY nie kierują ruchu na zewnątrz). Błąd, timeout albo odpowiedź inna niż 200 ⇒ `None` (ocena idzie dalej
samym modelem). Brak wykrytego błędu NIE jest dowodem poprawności wypowiedzi: `[]` ≠ „zdanie poprawne”.
Kontrakt (language, text, motherTongue, disabledCategories; matches[].offset/length/replacements/rule.id/issueType/category.id)
potwierdzony na żywym serwerze LT 6.6 (F4.6/C4). `language=en` bez odmiany wyłącza sprawdzanie pisowni.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import urlsplit

import requests

log = logging.getLogger(__name__)
ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1"}
MAX_TEXT = 2000
_warned = False


class LTConfigError(ValueError):
    pass


@dataclass(frozen=True)
class LTMatch:
    offset: int
    length: int
    message: str
    replacements: tuple[str, ...]
    rule_id: str
    issue_type: str
    category_id: str


def validate_url(url: str) -> str:
    u = urlsplit(url)
    if u.scheme not in ("http", "https") or u.username or u.password:
        raise LTConfigError("languagetool.url: dozwolony tylko http(s) bez danych logowania")
    if (u.hostname or "").lower() not in ALLOWED_HOSTS:
        raise LTConfigError(f"languagetool.url: tylko localhost/127.0.0.1/::1, jest {u.hostname!r}")
    return url.rstrip("/")


def settings(raw: dict | None = None) -> dict:
    from tutor import config
    c = {"enabled": False, "url": "http://127.0.0.1:8081", "timeout": 1.5, "language": "en-US",
         "mother_tongue": "pl", **((raw if raw is not None else config.raw_config()).get("languagetool") or {})}
    c["url"] = validate_url(c["url"])           # walidacja także przy enabled=false: zła konfiguracja nie przechodzi
    return c


def parse(payload: dict) -> list[LTMatch]:
    out = []
    for m in payload.get("matches", []):
        r = m.get("rule") or {}
        out.append(LTMatch(int(m["offset"]), int(m["length"]), m.get("message", ""),
                           tuple(x["value"] for x in m.get("replacements", []) if x.get("value")),
                           r.get("id", ""), r.get("issueType", ""), (r.get("category") or {}).get("id", "")))
    return out


def check(text: str, cfg: dict, *, disabled_categories: list[str] | None = None,
          session: requests.Session | None = None) -> list[LTMatch] | None:
    """Zwraca dopasowania albo `None` (wyłączony/niedostępny/timeout/błąd). Nigdy nie rzuca przy awarii sieci."""
    global _warned
    if not cfg.get("enabled"):
        return None
    url = validate_url(cfg["url"])
    s = session or requests.Session()
    s.trust_env = False
    data = {"language": cfg.get("language", "en-US"), "text": text[:MAX_TEXT]}
    if cfg.get("mother_tongue"):
        data["motherTongue"] = cfg["mother_tongue"]
    if disabled_categories:
        data["disabledCategories"] = ",".join(disabled_categories)
    try:
        r = s.post(url + "/v2/check", data=data, timeout=cfg.get("timeout", 1.5), allow_redirects=False)
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}")      # także 3xx: przekierowań nie śledzimy
        return parse(r.json())
    except (requests.RequestException, RuntimeError, ValueError, KeyError) as e:
        if not _warned:                                       # jeden wpis w logu na proces
            _warned = True
            log.warning("LanguageTool niedostępny (%s); oceniam bez niego", type(e).__name__)
        return None
