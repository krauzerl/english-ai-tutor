"""Ustawienia → Modele AI: opcjonalne Gemini per profil (klucz, zgoda, test połączenia, liczniki, model roli).

Domyślnie wszystko lokalne (Qwen3 8B przez Ollama). Gemini działa tylko, gdy profil ma: włączony przełącznik, zgodę,
klucz w magazynie sekretów i wybrany model dla danej roli. Do Google trafia wyłącznie treść potrzebna do bieżącej
odpowiedzi lub oceny (ten sam kontekst co dla Qwen3); Whisper i Kokoro zostają lokalne, audio nie jest wysyłane.
Te same walidatory, polityka korekt i blokady mastery obowiązują niezależnie od modelu.
"""
from __future__ import annotations

import threading
from datetime import UTC, datetime

from tutor.app import settings as ST
from tutor.llm import keystore
from tutor.llm.base import LLMError
from tutor.llm.route import Budget, Routed

# Kandydaci z briefu — pokazywani jako sugestia tylko wtedy, gdy API zwróci je dla klucza; nic nie wybieramy sami.
CANDIDATES = ("gemini-3.5-flash-lite", "gemini-4-hydrogen")
CHAT_TIMEOUT_S, EVAL_TIMEOUT_S, TEST_TIMEOUT_S = 15, 30, 20
CONSENT_PL = (
    "Po włączeniu Gemini tekst Twoich wypowiedzi (transkrypcja z Whispera) i potrzebny fragment bieżącej rozmowy "
    "opuszczają ten komputer i trafiają do Google (Gemini API). Nie wysyłamy nagrań audio, historii nauki, raportów "
    "ani bazy danych. W bezpłatnym planie Google może wykorzystywać przesłane treści do ulepszania usług, a ludzie "
    "mogą je czytać — nie podawaj danych osobowych ani poufnych. Warunki Gemini API wymagają ukończenia 18 lat; dla "
    "użytkowników z EOG, Szwajcarii i Wielkiej Brytanii udostępnianie aplikacji z API dopuszczają tylko w planie "
    "płatnym. Zgodę możesz w każdej chwili wycofać.")
USAGE_NOTE_PL = ("Liczniki tej aplikacji (żądania wysłane przez tutora), nie stan konta Google. Rzeczywiste limity i "
                 "ewentualne opłaty sprawdzisz tylko w Google AI Studio. Limit żądań na sesję nie gwarantuje braku "
                 "opłat w planie płatnym.")
TEST_MSG = {"auth": "Nieprawidłowy klucz API.", "model": "Model niedostępny.",
            "quota_day": "Osiągnięto dzienny limit API.", "quota_minute": "Osiągnięto limit API na minutę.",
            "quota": "Osiągnięto limit API.", "network": "Błąd połączenia.", "timeout": "Błąd połączenia (timeout).",
            "server": "Błąd połączenia (serwer Gemini).", "bad_request": "Gemini odrzuciło żądanie."}


def _gemini_cfg() -> dict:
    try:
        from tutor.llm import llm_settings
        return llm_settings()["gemini"]
    except Exception:  # noqa: BLE001 - błędny config.toml nie blokuje ustawień
        return {}


def sdk_available() -> bool:
    import importlib.util
    try:
        return importlib.util.find_spec("google.genai") is not None
    except ModuleNotFoundError:
        return False


NO_SDK_PL = 'Brak pakietu Gemini: zainstaluj `pip install -e ".[gemini]"`.'


def _provider(model: str, key: str, timeout: float):
    from tutor.llm.gemini import GeminiProvider
    return GeminiProvider(model, key, timeout, _gemini_cfg().get("thinking_budget"))


def usage(repo, pid: int) -> dict:
    day = datetime.now(UTC).strftime("%Y-%m-%dT00:00:00")
    q = ("SELECT COUNT(*), COALESCE(SUM(in_tokens),0), COALESCE(SUM(out_tokens),0) FROM llm_usage "
         "WHERE profile_id=? AND provider='gemini'")
    t = repo.conn.execute(q, (pid,)).fetchone()
    d = repo.conn.execute(q + " AND created_at>=?", (pid, day)).fetchone()
    return {"requests_today_utc": d[0], "tokens_today_utc": d[1] + d[2], "requests_total": t[0],
            "in_tokens_total": t[1], "out_tokens_total": t[2], "note": USAGE_NOTE_PL}


def status(repo, pid: int) -> dict:
    """Dla GUI: nigdy nie zwraca klucza i nie łączy się z Google."""
    v = ST.effective(repo, pid)
    return {"key": keystore.status(repo, pid), "persistent_store": keystore.persistent_available(),
            "consent_at": repo.get_profile(pid)["external_api_consent_at"], "consent_text": CONSENT_PL,
            "candidates": list(CANDIDATES), "usage": usage(repo, pid),
            "values": {k: v[k] for k in ("gemini_enabled", "chat_provider", "eval_provider", "gemini_chat_model",
                                         "gemini_eval_model", "gemini_max_requests", "chat_model")}}


def save_key(repo, pid: int, key: str, *, memory_only: bool = False) -> dict:
    where = keystore.save(repo, pid, key, persist=not memory_only)
    return {**status(repo, pid), "saved": where}


def _to_local(repo, pid: int) -> None:
    ST.update(repo, pid, {"chat_provider": "local", "eval_provider": "local"})


def delete_key(repo, pid: int) -> dict:
    keystore.delete(repo, pid)
    _to_local(repo, pid)                       # bez klucza Gemini nie może być wybrany
    return status(repo, pid)


def set_consent(repo, pid: int, accept: bool) -> dict:
    repo.set_consent(pid, accept)
    if not accept:
        ST.update(repo, pid, {"gemini_enabled": False, "chat_provider": "local", "eval_provider": "local"})
    return status(repo, pid)


def test_connection(repo, pid: int, model: str | None = None, *, make=None) -> dict:
    """1) klucz, 2) lista modeli, 3) modele z `generateContent`, 4) minimalne wywołanie wybranego modelu (stały tekst,
    bez danych ucznia). Samo pobranie listy nie jest potwierdzeniem generowania. Wywoływane tylko na żądanie."""
    key = keystore.get(repo, pid)
    if not key:
        return {"ok": False, "code": "no_key", "message": "Brak klucza API w tym profilu.", "models": []}
    model = ST._coerce("gemini_chat_model", model or "")
    if make is None and not sdk_available():
        return {"ok": False, "code": "no_sdk", "message": NO_SDK_PL, "models": []}
    p = (make or _provider)(model or "probe", key, TEST_TIMEOUT_S)
    try:
        models = p.list_text_models()
    except LLMError as e:
        return {"ok": False, "code": e.reason or "error", "message": TEST_MSG.get(e.reason, e.user_message),
                "models": []}
    out = {"models": models, "candidates": [c for c in CANDIDATES if c in models]}
    if not model:
        return {**out, "ok": False, "code": "pick", "message": f"Pobrano listę modeli ({len(models)}). Wybierz model "
                "i kliknij ponownie, by sprawdzić generowanie odpowiedzi."}
    if model not in models:
        return {**out, "ok": False, "code": "model", "message": TEST_MSG["model"], "model": model}
    try:
        r = p.ping()
    except LLMError as e:
        return {**out, "ok": False, "code": e.reason or "error", "message": TEST_MSG.get(e.reason, e.user_message),
                "model": model}
    repo.add_llm_usage(pid, "gemini", model, "test", r.usage.in_tokens, r.usage.billed_out, r.usage.latency_ms, None)
    return {**out, "ok": True, "code": "ok", "model": model, "latency_ms": r.usage.latency_ms,
            "message": f"Połączenie z Gemini działa ({model}, {r.usage.latency_ms} ms)."}


class _ThreadRepo:
    """Repo dla bieżącego wątku: wątek właściciela używa głównego połączenia, wątek oceny — własnego (SQLite)."""

    def __init__(self, repo):
        self.repo, self.owner, self.local = repo, threading.get_ident(), threading.local()
        self.path = repo.conn.execute("PRAGMA database_list").fetchone()[2]

    def get(self):
        if threading.get_ident() == self.owner:
            return self.repo
        r = getattr(self.local, "repo", None)
        if r is None and self.path:
            from tutor.store.db import open_db
            from tutor.store.repo import Repo
            r = self.local.repo = Repo(open_db(self.path))
        return r


def session_budget(repo, pid: int) -> Budget:
    return Budget(int(ST.effective(repo, pid)["gemini_max_requests"]))


def build(repo, pid: int, role: str, local, *, budget: Budget, sid=lambda: None, notify=None,
          prompt: str | None = None) -> Routed:
    """Model roli (`conversation` | `evaluation`) dla profilu. Bez kompletnej konfiguracji Gemini = sam `local`
    (opakowany tylko po to, by zapisać metadane wywołań w dzienniku nauki)."""
    from tutor.app import learnlog as LL
    v = ST.effective(repo, pid)
    short = "chat" if role == "conversation" else "eval"
    tr = _ThreadRepo(repo)
    primary = None
    if v["gemini_enabled"] and v[f"{short}_provider"] == "gemini" and v[f"gemini_{short}_model"]:
        key = keystore.get(repo, pid)
        if not sdk_available():
            if notify:
                notify(f"[{NO_SDK_PL} Używam lokalnego modelu.]")
        elif key and repo.get_profile(pid)["external_api_consent_at"]:
            t = _gemini_cfg().get("timeout") or (CHAT_TIMEOUT_S if role == "conversation" else EVAL_TIMEOUT_S)
            primary = _provider(v[f"gemini_{short}_model"], key, t)
        elif notify:
            notify("[Gemini wybrane, ale brak klucza lub zgody w profilu — używam lokalnego modelu.]")

    def gate() -> None:                        # zgoda sprawdzana przy każdym żądaniu (można ją wycofać w trakcie)
        r = tr.get()
        p = r.get_profile(pid) if r else None
        if not p or not p["external_api_consent_at"]:
            raise LLMError("Brak zgody na Gemini w tym profilu.", reason="consent")

    def on_event(ev: dict) -> None:
        r = tr.get()
        if r is None:
            return
        if ev["provider"] == "gemini":         # każde żądanie do Google (też nieudane); koszt nieznany = None, nie 0
            r.add_llm_usage(pid, "gemini", ev["model"], role, ev["in_tokens"] or 0, ev["out_tokens"] or 0,
                            ev["latency_ms"], None)
        LL.log(r, pid, "log.llm", sid(), **ev)

    r = Routed(role, local, primary, budget=budget, gate=gate, on_event=on_event, notify=notify, prompt=prompt)
    budget.routes.append(r)
    return r


def restore(budget: Budget) -> str:
    """Polecenie `/gemini` w sesji: kończy okres wyłączenia Gemini (zły klucz/limit i tak wrócą jako błąd)."""
    ok = [r.restore() for r in budget.routes]
    return "[Gemini przywrócone — następna odpowiedź spróbuje Gemini.]" if any(ok) else \
        "[Gemini nie jest wybrane w tym profilu (Ustawienia → Modele AI).]"


def chosen(repo, pid: int) -> dict:
    """Do metadanych sesji: wybór profilu (nie gwarancja, że każde wywołanie poszło do tego modelu — to w log.llm)."""
    v = ST.effective(repo, pid)
    on = v["gemini_enabled"]
    return {"chat": v["gemini_chat_model"] if on and v["chat_provider"] == "gemini" else "local",
            "eval": v["gemini_eval_model"] if on and v["eval_provider"] == "gemini" else "local"}
