"""Ustawienia LLM z config.toml i fabryka dostawców (wybór per rola)."""
from __future__ import annotations

from tutor import config
from tutor.llm.base import LLMError, LLMProvider
from tutor.llm.meter import Limits, Meter, Price
from tutor.llm.ollama import DEFAULT_MODEL, DEFAULT_URL, OllamaProvider

ROLES = ("conversation", "evaluation", "generation")
DEFAULT_WINDOW = 8192  # konserwatywnie, gdy model nie jest w [context_windows]
QWEN3_8B = "qwen3:8b"
# F4.7 (wyniki wstępne): Qwen3 8B bez thinking do rozmowy i oceny; Bielik do polskich tekstów.
# Domyślne ustawienia roli stosujemy tylko, gdy użytkownik nie podał modelu (np. własny wybór Bielika bez `think`).
ROLE_DEFAULTS = {"conversation": {"model": QWEN3_8B, "think": False},
                 "evaluation": {"model": QWEN3_8B, "think": False},
                 "generation": {"model": DEFAULT_MODEL}}


def _prices(raw: dict) -> dict[str, Price]:
    out = {}
    for model, p in raw.items():
        try:
            out[model] = Price(float(p["in_per_mtok"]), float(p["out_per_mtok"]))
        except (KeyError, TypeError, ValueError):
            raise LLMError(f"Cennik modelu '{model}': podaj dodatnie in_per_mtok i out_per_mtok "
                           "(zero nie jest domyślną ceną).") from None
    return out


def llm_settings() -> dict:
    raw = config.raw_config()
    llm = raw.get("llm", {})
    roles = {}
    for r in ROLES:
        c = {"provider": "ollama", **llm.get(r, {})}
        if c["provider"] == "ollama" and "model" not in c:  # domyślny model tylko lokalny; Gemini wymaga nazwy
            c = {**ROLE_DEFAULTS[r], **c}
        roles[r] = c
    lim = raw.get("limits", {})
    return {
        "roles": roles,
        "limits": {"daily_usd": lim.get("daily_usd"), "monthly_usd": lim.get("monthly_usd")},
        "prices": _prices(raw.get("pricing", {})),
        "ollama": llm.get("ollama", {}),
        "gemini": llm.get("gemini", {}),
        "context_windows": raw.get("context_windows", {}),
    }


def build_provider(role: str, settings: dict | None = None) -> LLMProvider:
    s = settings or llm_settings()
    cfg = s["roles"][role]
    if cfg["provider"] == "ollama":
        o = s["ollama"]
        return OllamaProvider(cfg["model"], o.get("url", DEFAULT_URL), o.get("num_ctx", 8192),
                              o.get("timeout", 120), o.get("keep_alive"), cfg.get("think", o.get("think")))
    if cfg["provider"] == "gemini":
        key = config.gemini_api_key()
        if not key:
            raise LLMError("Brak GEMINI_API_KEY: dodaj go do ~/.config/english-ai-tutor/.env.")
        if not cfg.get("model"):
            raise LLMError(f"Ustaw model Gemini dla roli '{role}' w config.toml.")
        from tutor.llm.gemini import GeminiProvider
        g = s["gemini"]
        return GeminiProvider(cfg["model"], key, g.get("timeout", 60), g.get("thinking_budget"))
    raise LLMError(f"Nieznany dostawca: {cfg['provider']}")


def build_meter(repo, settings: dict | None = None) -> Meter:
    s = settings or llm_settings()
    return Meter(repo, Limits(**s["limits"]), s["prices"])


def context_window(model: str, settings: dict | None = None) -> int:
    return int((settings or llm_settings())["context_windows"].get(model, DEFAULT_WINDOW))
