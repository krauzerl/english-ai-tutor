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
        elif args.cmd == "delete":
            if not args.yes:
                print("Usunięcie jest nieodwracalne. Dodaj --yes, aby potwierdzić.",
                      file=sys.stderr)
                return 1
            repo.delete_profile(p["id"])
            if config.get_last_profile() == p["id"]:
                config.set_last_profile(None)
            print(f"Usunięto profil {p['name']} wraz z danymi.")
        return 0
    finally:
        conn.close()


def content_main(argv: list[str], inp=input, out=print) -> int:
    """python main.py content validate|review <lang>."""
    import types
    from datetime import UTC, datetime

    from tutor.pedagogy import content as C

    ap = argparse.ArgumentParser(prog="main.py content")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("validate").add_argument("lang")
    sub.add_parser("attribution").add_argument("lang")
    rv = sub.add_parser("review")
    rv.add_argument("lang")
    rv.add_argument("--reviewer", required=True, help="id z reviewers.yaml")
    rv.add_argument("--all", action="store_true", help="także zadania już ocenione (poza human_reviewed)")
    rv.add_argument("--kind", choices=["items", "docs"], default="items",
                    help="items = zadania (domyślnie); docs = wyjaśnienia, scenariusze i zwroty")
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
    if args.kind == "docs":
        queue = [t for t in C.review_targets(pack) if t["status"] not in skip]
    else:
        queue = [i for i in pack.items.values() if i.review.status not in skip]
    out(f"Do przeglądu: {len(queue)}. [a]kceptuj  [e]dytuj notatkę  [o]drzuć  [p]omiń  [q]uit")
    done = 0
    for it in queue:
        if args.kind == "docs":
            out(f"\n{it['kind']} {it['id']}  status={it['status']}")
            for ln in it["lines"]:
                out("  " + ln)
            doc = it
            it = types.SimpleNamespace(id=it["id"], review=types.SimpleNamespace(notes=it["notes"]))
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
