"""Zarządzanie profilami: python main.py profile create|list|select|export|delete."""
import argparse
import json
import os
import sqlite3
import sys

from tutor import config
from tutor.store.db import open_db
from tutor.store.repo import Repo


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="main.py profile")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("create").add_argument("name")
    sub.add_parser("list")
    sub.add_parser("select").add_argument("profile")
    ex = sub.add_parser("export")
    ex.add_argument("profile")
    ex.add_argument("-o", "--output")
    de = sub.add_parser("delete")
    de.add_argument("profile")
    de.add_argument("--yes", action="store_true", help="potwierdź nieodwracalne usunięcie")
    de.add_argument("--no-backup", action="store_true", help="bez kopii zapasowej (domyślnie kopia JSON)")
    rs = sub.add_parser("reset", help="reset postępów: zostaje profil i ustawienia")
    rs.add_argument("profile")
    rs.add_argument("--yes", action="store_true", help="potwierdź reset postępów")
    rs.add_argument("--no-backup", action="store_true", help="bez kopii zapasowej (domyślnie kopia JSON)")
    args = ap.parse_args(argv)

    conn = open_db(config.db_path())
    repo = Repo(conn)
    try:
        if args.cmd == "create":
            try:
                pid = repo.create_profile(args.name)
            except sqlite3.IntegrityError:
                print(f"Profil '{args.name}' już istnieje lub nazwa jest pusta.", file=sys.stderr)
                return 1
            config.set_last_profile(pid)
            print(f"Utworzono profil {pid}: {args.name}")
            return 0
        if args.cmd == "list":
            last = config.get_last_profile()
            for p in repo.list_profiles():
                print(f"{'*' if p['id'] == last else ' '} {p['id']}\t{p['name']}")
            return 0
        p = repo.find_profile(args.profile)
        if p is None:
            print(f"Brak profilu: {args.profile}", file=sys.stderr)
            return 1
        if args.cmd == "select":
            config.set_last_profile(p["id"])
            print(f"Wybrano: {p['name']}")
        elif args.cmd == "export":
            text = json.dumps(repo.export_profile(p["id"]), ensure_ascii=False, indent=2)
            if args.output:
                fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                os.fchmod(fd, 0o600)  # także gdy plik już istniał
                with os.fdopen(fd, "w") as f:
                    f.write(text)
            else:
                print(text)
        elif args.cmd in ("delete", "reset"):
            from tutor.app import profiles as PR
            if not args.yes:
                what = "Usunięcie profilu" if args.cmd == "delete" else "Reset postępów"
                print(f"{what} jest nieodwracalne (poza kopią zapasową). Dodaj --yes, aby potwierdzić.",
                      file=sys.stderr)
                return 1
            fn = PR.delete if args.cmd == "delete" else PR.reset_progress
            try:
                r = fn(repo, p["id"], p["name"], make_backup=not args.no_backup)
            except PR.ProfileOpError as e:
                print(str(e), file=sys.stderr)
                return 1
            if r["backup"]:
                print(f"Kopia zapasowa: {r['backup']}")
            print(f"Usunięto profil {p['name']} wraz z danymi." if args.cmd == "delete"
                  else f"Zresetowano postępy profilu {p['name']} (ustawienia zostały).")
        return 0
    finally:
        conn.close()


def content_main(argv: list[str], inp=input, out=print) -> int:
    """python main.py content validate|review <lang>."""
    import types
    from datetime import UTC, datetime

    import yaml

    from tutor.pedagogy import content as C

    ap = argparse.ArgumentParser(prog="main.py content")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("validate").add_argument("lang")
    sub.add_parser("attribution").add_argument("lang")
    rv = sub.add_parser("review")
    rv.add_argument("lang")
    rv.add_argument("--reviewer", required=True, help="id z reviewers.yaml")
    rv.add_argument("--all", action="store_true", help="także zadania już ocenione (poza human_reviewed)")
    rv.add_argument("--kind", choices=["items", "docs", "bench"], default="items",
                    help="items = zadania (domyślnie); docs = wyjaśnienia, scenariusze, zwroty; "
                         "bench = przypadki benchmarku (złoty standard)")
    args = ap.parse_args(argv)
    try:
        rep = C.validate(args.lang, extracted_dir=config.data_dir() / "content_sources" / "extracted")
    except C.ContentError as e:
        out("\n".join(e.report.errors))
        return 1
    if args.cmd == "validate":
        out(C.format_report(rep))
        return 0 if rep.ok else 1
    if args.cmd == "attribution":
        pack = C.load(args.lang)
        (pack.root / "ATTRIBUTION.md").write_text(C.attribution_md(pack.sources), encoding="utf-8")
        out(f"Zapisano {pack.root / 'ATTRIBUTION.md'}")
        return 0
    if not rep.ok:
        out(C.format_report(rep))
        out("Napraw błędy walidacji przed przeglądem.")
        return 1
    pack = C.load(args.lang)
    if args.reviewer not in {r.id for r in pack.reviewers.reviewers}:
        out(f"Reviewer „{args.reviewer}” nie występuje w reviewers.yaml (dodaj siebie ręcznie).")
        return 1
    skip = {"human_reviewed", "rejected"} if args.all else {"human_reviewed", "rejected", "suspect"}
    if args.kind == "bench":
        try:
            from bench import grammar as BG
        except ImportError:
            out("Moduł bench dostępny tylko w repozytorium źródłowym.")
            return 1
        queue = []
        for f, key in ((BG.CASES / "grammar_gold.yaml", "id"), (BG.CASES / "f3_mismatch.yaml", "item_id")):
            for d in yaml.safe_load(f.read_text(encoding="utf-8")):
                if d["review"]["status"] not in skip:
                    lines = ([f"{d['set']} [{d['input_mode']}] {d['text']}"]
                             + [f"  ZŁOTY: „{g['span']}” → {g['fix_accept']} ({g['category']})" for g in d["gold"]]
                             if "set" in d else [f"zadanie F3 {d['item_id']}: klucz człowieka = {d['human_key']}"])
                    queue.append({"kind": "bench", "id": d[key], "status": d["review"]["status"],
                                  "notes": d["review"].get("notes"), "lines": lines, "path": f})
    elif args.kind == "docs":
        queue = [t for t in C.review_targets(pack) if t["status"] not in skip]
    else:
        queue = [i for i in pack.items.values() if i.review.status not in skip]
    out(f"Do przeglądu: {len(queue)}. [a]kceptuj  [e]dytuj notatkę  [o]drzuć  [p]omiń  [q]uit")
    done = 0
    for it in queue:
        if args.kind in ("docs", "bench"):
            out(f"\n{it['kind']} {it['id']}  status={it['status']}")
            for ln in it["lines"]:
                out("  " + ln)
            doc = it
            it = types.SimpleNamespace(id=it["id"], review=types.SimpleNamespace(notes=it["notes"]))
            if args.kind == "bench":
                save = lambda st, d=doc, **kw: C.set_review_bench(pack, d["path"], d["id"], st, **kw)  # noqa: E731
            else:
                save = lambda st, d=doc, **kw: C.set_review_doc(pack, d["kind"], d["id"], st, **kw)  # noqa: E731
            note = lambda n: None  # noqa: E731  (notatka dla dokumentów: w treści wpisu review.notes po decyzji)
        else:
            out(f"\n{it.id}  {it.area}/{it.cefr}/{it.type}  status={it.review.status}  źródło={it.provenance.source}")
            if it.stimulus:
                out(f"  TEKST: {it.stimulus}")
            if it.audio_text:
                out(f"  AUDIO: {it.audio_text}")
            out(f"  ZADANIE: {it.prompt}")
            if it.options:
                out("  OPCJE: " + " | ".join(it.options))
            out(f"  KLUCZ: {it.answers}")
            out(f"  WYJAŚNIENIE: {it.explanation_pl}")
            save = lambda st, _id=it.id, **kw: C.set_review(pack, _id, st, **kw)  # noqa: E731
            note = lambda n, _id=it.id: C.set_note(pack, _id, n)  # noqa: E731
        if it.review.notes:
            out(f"  NOTATKA: {it.review.notes}")
        notes = it.review.notes
        while True:
            c = inp("> ").strip().lower()[:1]
            now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            if c == "a":
                save("human_reviewed", reviewer=args.reviewer, now=now, notes=notes)
            elif c == "o":
                save("rejected", reviewer=args.reviewer, now=now, notes=inp("powód odrzucenia: ").strip() or None)
            elif c == "e":
                notes = inp("notatka: ").strip() or None
                note(notes)
                continue  # po notatce nadal czekamy na decyzję
            elif c == "p":
                break
            elif c == "q":
                out(f"Zakończono; zapisano {done}.")
                return 0
            else:
                continue
            done += 1
            break
    out(f"Koniec kolejki; zapisano {done}.")
    return 0


def logs_main(argv: list[str], out=print) -> int:
    """Dziennik nauki: python main.py logs path|report|export|flag|on|off|delete|prune."""
    from tutor.app import learning_report as LR
    from tutor.app import learnlog as LL
    from tutor.pedagogy import content as C
    ap = argparse.ArgumentParser(prog="main.py logs")
    ap.add_argument("--profile", help="nazwa lub id profilu (domyślnie ostatnio wybrany)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("path", help="gdzie są pliki dziennika")
    for name, days in (("report", 7), ("export", 30)):
        x = sub.add_parser(name)
        x.add_argument("--days", type=int, default=days, help=f"okres w dniach (domyślnie {days}; 0 = całość)")
        x.add_argument("--session", type=int, help="tylko jedna sesja (id)")
        if name == "export":
            x.add_argument("--no-redact", action="store_true", help="bez automatycznej redakcji (pełne wypowiedzi)")
            x.add_argument("--redact-word", action="append", default=[], help="dodatkowe słowo do ukrycia")
    fl = sub.add_parser("flag", help="zgłoszenie problemu nauczyciela (niezweryfikowane)")
    fl.add_argument("kind", choices=sorted(LL.REPORT_KINDS))
    fl.add_argument("--session", type=int)
    fl.add_argument("--observation", type=int, help="id korekty z dziennika")
    fl.add_argument("--quote", help="fragment wypowiedzi")
    fl.add_argument("--note", help="uwaga, np. poprawna forma")
    sub.add_parser("on", help="włącz szczegółowy dziennik")
    sub.add_parser("off", help="wyłącz szczegółowy dziennik (zgłoszenia nadal zapisywane)")
    de = sub.add_parser("delete", help="usuń pliki dziennika i zdarzenia dziennika profilu (historia nauki zostaje)")
    de.add_argument("--yes", action="store_true")
    pr = sub.add_parser("prune", help="usuń pliki JSONL starsze niż N dni")
    pr.add_argument("--days", type=int, default=LL.RETENTION_DAYS)
    a = ap.parse_args(argv)
    conn = open_db(config.db_path())
    repo = Repo(conn)
    try:
        if a.cmd == "prune":
            out(f"Usunięto plików: {LL.prune(repo, a.days)}")
            return 0
        if a.cmd == "path":
            out(str(LL.logs_dir(repo)))
            return 0
        p = repo.find_profile(a.profile) if a.profile else repo.get_profile(config.get_last_profile() or -1)
        if p is None:
            print("Brak profilu: podaj --profile NAZWA", file=sys.stderr)
            return 1
        pid = p["id"]
        if a.cmd in ("on", "off"):
            repo.set_setting(pid, "learning_log", a.cmd == "on")
            out(f"Szczegółowy dziennik nauki: {'włączony' if a.cmd == 'on' else 'wyłączony'}")
        elif a.cmd == "delete":
            if not a.yes:
                print("Usunięcie plików dziennika jest nieodwracalne. Dodaj --yes.", file=sys.stderr)
                return 1
            r = LL.delete_profile_logs(repo, pid)
            out(f"Usunięto plików: {r['files']}, zdarzeń dziennika: {r['events']} (historia nauki została).")
        elif a.cmd == "flag":
            try:
                r = LL.report(repo, pid, a.kind, session_id=a.session, observation_id=a.observation, quote=a.quote,
                              note=a.note)
            except ValueError as e:
                print(f"Nie można zapisać zgłoszenia: {e}", file=sys.stderr)
                return 1
            out(f"Zapisano zgłoszenie #{r['id']} ({LL.REPORT_KINDS[a.kind]}), sesja #{r['session_id']}. "
                "Status: niezweryfikowane.")
        else:
            pack = C.load(p["target_lang"])
            if a.cmd == "report":
                out(str(LR.write_report(repo, pack, pid, days=a.days or None, session_id=a.session)))
            else:
                d = LR.export(repo, pack, pid, days=a.days or None, session_id=a.session, redacted=not a.no_redact,
                              extra_words=a.redact_word)
                out(str(d))
                out("Przejrzyj pliki ręcznie przed udostępnieniem (redakcja automatyczna nie jest kompletna).")
        return 0
    finally:
        conn.close()
