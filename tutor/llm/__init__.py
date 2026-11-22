"""Ustawienia LLM z config.toml i fabryka dostawców (wybór per rola)."""
from __future__ import annotations

from tutor import config
from tutor.llm.base import LLMError, LLMProvider
from tutor.llm.meter import Limits, Meter, Price
from tutor.llm.ollama import DEFAULT_MODEL, DEFAULT_URL, OllamaProvider

ROLES = ("conversation", "evaluation", "generation")
DEFAULT_WINDOW = 8192  # konserwatywnie, gdy model nie jest w [context_windows]


def llm_settings() -> dict:
    raw = config.raw_config()
    llm = raw.get("llm", {})
    roles = {}
    for r in ROLES:
        c = {"provider": "ollama", **llm.get(r, {})}
        if c["provider"] == "ollama":  # domyślny model tylko lokalny; Gemini wymaga jawnej nazwy
            c.setdefault("model", DEFAULT_MODEL)
        roles[r] = c
    lim = raw.get("limits", {})
    return {
        "roles": roles,
        "limits": {"daily_usd": lim.get("daily_usd"), "monthly_usd": lim.get("monthly_usd")},
        "prices": {m: Price(float(p["in_per_mtok"]), float(p["out_per_mtok"]))
                   for m, p in raw.get("pricing", {}).items()},
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
                              o.get("timeout", 120), o.get("keep_alive"))
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
