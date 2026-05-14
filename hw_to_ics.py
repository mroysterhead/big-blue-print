#!/usr/bin/env python3
"""
Fetch the 6A weekly homework Google Doc, parse the assignments table,
and emit an .ics file with one all-day event per assignment due-date.

Usage:
    python3 hw_to_ics.py [--doc-id ID] [--out path.ics]

Default doc is the 6A Eastars homework doc.
"""

import argparse
import re
import sys
import urllib.request
import uuid
from datetime import date, datetime, timedelta, timezone

DEFAULT_DOC_ID = "1meoCQmChHp1HJwj-IximTILDL_4qVc7xdCDuUu-YLdI"
DEFAULT_OUT = "homework.ics"

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
SUBJECTS = ["Math", "ELA", "Science", "Social Studies"]


def fetch_doc(doc_id: str) -> str:
    url = f"https://docs.google.com/document/d/{doc_id}/export?format=txt"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req) as r:
        return r.read().decode("utf-8-sig")


def parse_week_start(text: str) -> date:
    """Find the first M/D/YY date in the doc and snap to that week's Monday."""
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", text)
    if not m:
        raise ValueError("No date found in document header")
    mo, da, yr = (int(x) for x in m.groups())
    if yr < 100:
        yr += 2000
    d = date(yr, mo, da)
    # Snap to Monday of that week (or next Monday if header date is Sat/Sun)
    if d.weekday() == 0:
        return d
    if d.weekday() >= 5:  # Sat/Sun -> next Monday
        return d + timedelta(days=7 - d.weekday())
    return d - timedelta(days=d.weekday())  # Tue-Fri -> back to Mon


def tokenize_cells(text: str) -> list[str]:
    """Google Docs exports tables with each cell starting with a tab at line-start.
    Cells may contain newlines until the next \\t-prefixed line."""
    cells: list[str] = []
    current: list[str] = []
    for line in text.splitlines():
        if line.startswith("\t"):
            if current:
                cells.append("\n".join(current).strip())
            current = [line[1:]]
        else:
            if current:
                current.append(line)
    if current:
        cells.append("\n".join(current).strip())
    return cells


def parse_assignments(text: str, week_start: date) -> list[dict]:
    """Walk the cells and return [{subject, day_idx, raw_line}, ...] for HW lines.

    Layout per subject block: 1 subject cell + 5 CW cells + 5 HW cells.
    """
    cells = tokenize_cells(text)

    # Find "Monday" anchor
    try:
        mon_idx = next(i for i, c in enumerate(cells) if c.strip() == "Monday")
    except StopIteration:
        raise ValueError("Could not find 'Monday' header in document")

    # Skip past the header row (Mon..Fri + possibly an Announcements cell)
    # The first subject cell is the next cell that starts with a known subject name.
    i = mon_idx + 5
    assignments: list[dict] = []

    while i < len(cells):
        # Find next subject cell
        while i < len(cells) and not _matches_subject(cells[i]):
            i += 1
        if i >= len(cells):
            break
        subject = _matches_subject(cells[i])
        i += 1
        # Next 5 cells = CW (skip), next 5 = HW
        if i + 10 > len(cells):
            break
        hw_cells = cells[i + 5 : i + 10]
        for day_idx, hw in enumerate(hw_cells):
            for line in _split_hw_lines(hw):
                assignments.append(
                    {"subject": subject, "day_idx": day_idx, "raw": line}
                )
        i += 10

    return assignments


def _matches_subject(cell: str) -> str | None:
    head = cell.strip().splitlines()[0].strip() if cell.strip() else ""
    for s in SUBJECTS:
        if head.lower().startswith(s.lower()):
            return s
    return None


def _split_hw_lines(cell: str) -> list[str]:
    """Strip the 'HW:' prefix and return non-trivial lines."""
    body = re.sub(r"^\s*HW\s*:\s*", "", cell, flags=re.IGNORECASE).strip()
    out = []
    for raw in body.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.lower() in {"none", "n/a", "no hw", "no homework"}:
            continue
        out.append(line)
    return out


DAY_ABBREVS = {
    "mon": 0, "monday": 0,
    "tue": 1, "tues": 1, "tuesday": 1,
    "wed": 2, "weds": 2, "wednesday": 2,
    "thu": 3, "thur": 3, "thurs": 3, "thursday": 3,
    "fri": 4, "friday": 4,
}
DUE_DAY_RE = re.compile(
    r"\bdue\s+(today|tomorrow|" + "|".join(sorted(DAY_ABBREVS, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)


def resolve_due_date(line: str, day_idx: int, week_start: date) -> date:
    m = DUE_DAY_RE.search(line)
    if m:
        word = m.group(1).lower()
        if word == "today":
            target = day_idx
        elif word == "tomorrow":
            target = day_idx + 1
        else:
            target = DAY_ABBREVS[word]
        target = max(0, min(4, target))
        return week_start + timedelta(days=target)
    return week_start + timedelta(days=day_idx)


def normalize(line: str) -> str:
    """For dedup: strip 'due X' phrases and collapse whitespace."""
    s = DUE_DAY_RE.sub("", line)
    s = re.sub(r"\s+", " ", s).strip(" .!,")
    return s.lower()


def build_events(assignments: list[dict], week_start: date) -> list[dict]:
    """Dedupe by (subject, normalized text), keeping the earliest due date."""
    by_key: dict[tuple, dict] = {}
    for a in assignments:
        key = (a["subject"], normalize(a["raw"]))
        due = resolve_due_date(a["raw"], a["day_idx"], week_start)
        if key in by_key:
            if due < by_key[key]["due"]:
                by_key[key]["due"] = due
        else:
            by_key[key] = {
                "subject": a["subject"],
                "title": a["raw"],
                "due": due,
            }
    return sorted(by_key.values(), key=lambda e: (e["due"], e["subject"]))


def ics_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;").replace("\n", "\\n")


def render_ics(events: list[dict]) -> str:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//6A Eastars HW//EN",
        "CALSCALE:GREGORIAN",
    ]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for ev in events:
        d = ev["due"].strftime("%Y%m%d")
        d_end = (ev["due"] + timedelta(days=1)).strftime("%Y%m%d")
        title = f"{ev['subject']}: {ev['title'].splitlines()[0][:80]}"
        lines += [
            "BEGIN:VEVENT",
            f"UID:{uuid.uuid4()}@hw_to_ics",
            f"DTSTAMP:{stamp}",
            f"DTSTART;VALUE=DATE:{d}",
            f"DTEND;VALUE=DATE:{d_end}",
            f"SUMMARY:{ics_escape(title)}",
            f"DESCRIPTION:{ics_escape(ev['title'])}",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def format_table(headers: list[str], rows: list[tuple], style: str) -> str:
    cols = list(zip(headers, *rows)) if rows else [(h,) for h in headers]
    widths = [max(len(str(c)) for c in col) for col in cols]

    def fmt_row(cells):
        return "| " + " | ".join(str(c).ljust(w) for c, w in zip(cells, widths)) + " |"

    if style == "markdown":
        sep = "| " + " | ".join("-" * w for w in widths) + " |"
    else:
        bar = "+" + "+".join("-" * (w + 2) for w in widths) + "+"
        sep = bar

    out = []
    if style == "ascii":
        out.append(sep)
    out.append(fmt_row(headers))
    out.append(sep)
    for r in rows:
        out.append(fmt_row(r))
    if style == "ascii":
        out.append(sep)
    return "\n".join(out)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--doc-id", default=DEFAULT_DOC_ID)
    p.add_argument("--out", default=DEFAULT_OUT)
    p.add_argument("--format", choices=["ascii", "markdown"], default="ascii",
                   help="Table format (default: ascii)")
    p.add_argument("--quiet", action="store_true", help="Suppress the table output")
    args = p.parse_args()

    text = fetch_doc(args.doc_id)
    week_start = parse_week_start(text)
    raw = parse_assignments(text, week_start)
    events = build_events(raw, week_start)

    print(f"Week of {week_start:%a %b %d, %Y}", file=sys.stderr)
    print(f"Parsed {len(raw)} HW lines, {len(events)} unique assignments", file=sys.stderr)

    if not args.quiet:
        rows = [
            (f"{ev['due']:%a} {ev['due'].month}/{ev['due'].day}",
             ev["subject"],
             ev["title"].splitlines()[0])
            for ev in events
        ]
        print(format_table(["Due", "Subject", "Assignment"], rows, args.format))

    with open(args.out, "w") as f:
        f.write(render_ics(events))
    print(f"Wrote {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
