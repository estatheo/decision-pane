#!/usr/bin/env python3
"""Decisions and Work of the day for Gas City agents on any model.

Writes to city beads, shared by the local browser panel and the Claude Code
mod in this repository (with its store set to "beads"). Standard library only.

  gc decisions ask "Question?" --option "Label :: what happens" --option "Other" [--context ..] [--recommend 1]
  gc decisions work KEY [--title ..] [--status todo|running|waiting|review|blocked|done|dropped] [--note ..]
  gc decisions list
  gc decisions withdraw ID [ID ...]
"""
import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys

STATUSES = ["todo", "running", "waiting", "review", "blocked", "done", "dropped"]
FINISHED = {"done", "dropped"}


def gc_bin():
    found = os.environ.get("GC_BIN") or shutil.which("gc")
    if found:
        return found
    fallback = os.path.expanduser("~/.local/bin/gc")
    return fallback if os.path.exists(fallback) else "gc"


def bd(*args):
    cmd = [gc_bin(), "bd"]
    if os.environ.get("GC_CITY_PATH"):
        cmd += ["--city", os.environ["GC_CITY_PATH"]]
    run = subprocess.run(cmd + list(args), capture_output=True, text=True)
    if run.returncode != 0:
        sys.exit(f"gc bd {' '.join(args[:1])} failed: {run.stderr.strip()[-400:]}")
    return run.stdout


def beads(label, include_closed=False):
    args = ["list", "--label", label, "--json", "--limit", "0"]
    if include_closed:
        args += ["--all", "--updated-after", (dt.date.today() - dt.timedelta(days=1)).isoformat()]
    out = bd(*args)
    start = out.find("[")
    return json.loads(out[start:]) if start >= 0 else []


def me():
    return os.environ.get("GC_ALIAS") or os.environ.get("GC_SESSION_ID") or os.environ.get("GC_AGENT") or ""


def ask(a):
    options = []
    for raw in a.option:
        label, _, detail = raw.partition("::")
        if label.strip():
            options.append({"label": label.strip(), **({"detail": detail.strip()} if detail.strip() else {})})
    if not 2 <= len(options) <= 9:
        sys.exit("A decision needs 2 to 9 --option values.")
    meta = {
        "kind": "decision",
        "options": options,
        "from": a.sender or os.environ.get("GC_AGENT") or "",
        "reply_to": a.reply_to or me(),
    }
    if a.recommend:
        if not 1 <= a.recommend <= len(options):
            sys.exit("--recommend is the option's number, 1 first.")
        meta["recommended"] = a.recommend - 1
    out = bd("create", a.question, "--labels", "decision", "--description", a.context or "",
             "--allow-empty-description", "--metadata", json.dumps(meta), "--silent")
    bead = out.strip().splitlines()[-1] if out.strip() else "?"
    print(f'Posted {bead} to the Decisions panel. The answer arrives as mail whose subject starts '
          f'"DECISION {bead}:". Carry on with other work meanwhile.')


def find_work(key):
    for b in beads("work"):
        if (b.get("metadata") or {}).get("key") == key:
            return b
    return None


def work(a):
    if a.status and a.status not in STATUSES:
        sys.exit(f"--status is one of {', '.join(STATUSES)}.")
    fields = {k: getattr(a, k) for k in ["note", "who", "link", "group", "due"] if getattr(a, k) is not None}
    if a.order is not None:
        fields["order"] = a.order
    if a.status:
        fields["status"] = a.status
    found = find_work(a.key)
    if found:
        args = ["update", found["id"], "--metadata", json.dumps(fields)]
        if a.title:
            args += ["--title", a.title]
        bd(*args)
        bead = found["id"]
    else:
        if not a.title:
            sys.exit(f"{a.key} is not on the list yet: give --title to add it.")
        meta = {"kind": "work", "key": a.key, "status": a.status or "todo", "day": dt.date.today().isoformat(), **fields}
        bead = bd("create", a.title, "--labels", "work", "--allow-empty-description",
                  "--metadata", json.dumps(meta), "--silent").strip().splitlines()[-1]
    if a.status in FINISHED:
        bd("close", bead, "--reason", a.status)
    print(f"{a.key} updated ({bead}).")


def show(_a):
    open_d = [b for b in beads("decision")]
    print(f"Waiting on the user ({len(open_d)}):" if open_d else "Nothing waiting on the user.")
    for b in open_d:
        print(f"- {b['id']}: {b['title']}")
    items = beads("work")
    print()
    print("Work:" if items else "The work list is empty.")
    for b in items:
        m = b.get("metadata") or {}
        note = f" ({m['note']})" if m.get("note") else ""
        group = f"{m['group']} / " if m.get("group") else ""
        print(f"- {group}{m.get('key', b['id'])} [{m.get('status', 'todo')}] {b['title']}{note}")


def withdraw(a):
    for bead in a.ids:
        bd("update", bead, "--metadata", json.dumps({"withdrawn": True}))
        bd("close", bead, "--reason", "withdrawn")
    print(f"Withdrawn: {', '.join(a.ids)}.")


def main(argv):
    p = argparse.ArgumentParser(prog="gc decisions")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("ask", help="Put a decision in the human's Decisions panel")
    s.add_argument("question")
    s.add_argument("--option", action="append", default=[], help='"Label :: what happens if picked" (2 to 9)')
    s.add_argument("--context", help="What the human needs to know to choose, 1 to 4 short lines")
    s.add_argument("--recommend", type=int, help="Number of the option you recommend, 1 first")
    s.add_argument("--from", dest="sender", help="Who raised it (default: $GC_AGENT)")
    s.add_argument("--reply-to", help="Who gets the answer by gc mail (default: this session)")
    s.set_defaults(fn=ask)
    w = sub.add_parser("work", help="Add or update an item on the Work of the day list")
    w.add_argument("key")
    w.add_argument("--title")
    w.add_argument("--status")
    w.add_argument("--note")
    w.add_argument("--who")
    w.add_argument("--link")
    w.add_argument("--group")
    w.add_argument("--order", type=float)
    w.add_argument("--due")
    w.set_defaults(fn=work)
    sub.add_parser("list", help="Show open decisions and the work list").set_defaults(fn=show)
    d = sub.add_parser("withdraw", help="Remove open decisions that no longer need the human")
    d.add_argument("ids", nargs="+")
    d.set_defaults(fn=withdraw)
    a = p.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main(sys.argv[1:])
