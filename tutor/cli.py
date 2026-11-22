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
