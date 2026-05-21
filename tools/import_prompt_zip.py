#!/usr/bin/env python3
"""Stream a zipped .prompts file into the prompt database.

This is for large Dream Factory-style prompt packs where creating intermediate
JSON files is impractical.
"""

import argparse
import datetime
import hashlib
import html
import json
import re
import sqlite3
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prompt_library.db import DEFAULT_DB_PATH, get_connection
from clean_prompts import clean_positive_prompt, generate_concept, should_reject_prompt


PROMPTS_SECTION = re.compile(r"^\s*\[prompts\]\s*$", re.IGNORECASE)
CONFIG_SECTION = re.compile(r"^\s*\[config\]\s*$", re.IGNORECASE)
SETTING = re.compile(r"^!(\w+)\s*=\s*(.*)$")
SPACE = re.compile(r"\s+")
BRACED_LITERAL = re.compile(r"\{([^{}]*)\}")


def normalize_prompt(line):
    line = html.unescape(line.decode("utf-8", errors="ignore")).replace("\x00", "")
    line = SPACE.sub(" ", line).strip()
    if len(line) >= 2 and line[0] == line[-1] and line[0] in {"'", '"'}:
        line = line[1:-1].strip()
    return line


def sanitize_literal_braces(text):
    """Raw prompt packs may use braces as prose, not prompt-library wildcards."""
    text = BRACED_LITERAL.sub(r"\1", text)
    return text.replace("__", "_")


def iter_prompts(zip_path, member_name=None):
    settings = {}
    in_prompts = False

    with zipfile.ZipFile(zip_path) as archive:
        if member_name is None:
            candidates = [name for name in archive.namelist() if name.lower().endswith(".prompts")]
            if len(candidates) != 1:
                raise ValueError(f"Expected exactly one .prompts member, found {len(candidates)}")
            member_name = candidates[0]

        with archive.open(member_name) as stream:
            for raw_line in stream:
                line = normalize_prompt(raw_line)
                if not line or line.startswith("#"):
                    continue
                if CONFIG_SECTION.match(line):
                    in_prompts = False
                    continue
                if PROMPTS_SECTION.match(line):
                    in_prompts = True
                    continue
                if not in_prompts:
                    match = SETTING.match(line)
                    if match:
                        settings[match.group(1)] = match.group(2).strip()
                    continue
                yield line, settings


def ensure_style(cursor):
    cursor.execute(
        """
        INSERT OR IGNORE INTO prompt_style_profiles
            (identifier, syntax_family, negative_prompt_strategy, created_at)
        VALUES ('kkwprompt-raw', 'comma-separated', 'standard', datetime('now'))
        """
    )
    cursor.execute("SELECT id FROM prompt_style_profiles WHERE identifier = 'kkwprompt-raw'")
    return cursor.fetchone()["id"]


def existing_identifiers(cursor, prefix):
    cursor.execute("SELECT identifier FROM prompts WHERE identifier LIKE ?", (f"{prefix}_%",))
    return {row["identifier"] for row in cursor.fetchall()}


def insert_batch(cursor, rows, style_id, negative_prompt):
    for row in rows:
        cursor.execute(
            """
            INSERT INTO prompts
                (identifier, concept, status, metadata, created_at, updated_at)
            VALUES (?, ?, 'active', ?, datetime('now'), datetime('now'))
            """,
            (row["identifier"], row["concept"], json.dumps(row["metadata"])),
        )
        prompt_id = cursor.lastrowid
        cursor.execute(
            """
            INSERT INTO prompt_versions
                (prompt_id, version, change_type, changed_by, change_reason, created_at)
            VALUES (?, 1, 'created', 'import_prompt_zip', 'Imported from zipped .prompts source', datetime('now'))
            """,
            (prompt_id,),
        )
        cursor.execute(
            """
            INSERT INTO prompt_templates
                (prompt_id, style_profile_id, positive_template, negative_template, enabled, notes, created_at, updated_at)
            VALUES (?, ?, ?, ?, 1, ?, datetime('now'), datetime('now'))
            """,
            (prompt_id, style_id, row["positive"], negative_prompt, "Imported from kkwprompt zip"),
        )


def import_zip(zip_path, member_name=None, db_path=None, source_slug="kkwprompt", batch_size=5000, limit=None, dry_run=False):
    conn = get_connection(db_path)
    cursor = conn.cursor()
    style_id = ensure_style(cursor)
    existing = existing_identifiers(cursor, source_slug)
    seen = set(existing)
    imported = 0
    skipped = 0
    rejected = 0
    scanned = 0
    batch = []
    import_id = None
    started_at = datetime.datetime.now().isoformat()
    negative_prompt = ""

    if not dry_run:
        cursor.execute(
            """
            INSERT INTO imports (source_file, status, rows_imported, rows_skipped, created_at)
            VALUES (?, 'processing', 0, 0, ?)
            """,
            (str(zip_path), started_at),
        )
        import_id = cursor.lastrowid
        conn.commit()

    try:
        for raw_prompt, settings in iter_prompts(zip_path, member_name):
            scanned += 1
            if not negative_prompt:
                negative_prompt = settings.get("NEG_PROMPT", "")
            digest = hashlib.sha1(raw_prompt.encode("utf-8")).hexdigest()
            identifier = f"{source_slug}_{digest[:16]}"
            if identifier in seen:
                skipped += 1
                continue
            seen.add(identifier)

            metadata = {
                "original_source": source_slug,
                "date_added": started_at,
                "source_file": str(zip_path),
                "content_sha1": digest,
                "ingestion_path": "tools/import_prompt_zip.py",
            }
            cleaned = sanitize_literal_braces(clean_positive_prompt(raw_prompt, metadata))
            should_reject, _ = should_reject_prompt(cleaned, metadata)
            if should_reject:
                rejected += 1
                continue

            batch.append({
                "identifier": identifier,
                "concept": generate_concept(cleaned),
                "metadata": metadata,
                "positive": cleaned,
            })

            if len(batch) >= batch_size:
                if not dry_run:
                    insert_batch(cursor, batch, style_id, negative_prompt)
                    conn.commit()
                imported += len(batch)
                batch.clear()
                print(f"scanned={scanned} imported={imported} skipped={skipped} rejected={rejected}", flush=True)

            if limit and imported + len(batch) >= limit:
                break

        if batch:
            if not dry_run:
                insert_batch(cursor, batch, style_id, negative_prompt)
                conn.commit()
            imported += len(batch)

        if not dry_run:
            cursor.execute(
                """
                UPDATE imports
                SET status = 'completed', rows_imported = ?, rows_skipped = ?, completed_at = ?
                WHERE id = ?
                """,
                (imported, skipped + rejected, datetime.datetime.now().isoformat(), import_id),
            )
            conn.commit()

        return {"scanned": scanned, "imported": imported, "skipped": skipped, "rejected": rejected}
    except Exception as exc:
        if not dry_run and import_id is not None:
            cursor.execute(
                "UPDATE imports SET status = 'failed', error_log = ? WHERE id = ?",
                (str(exc), import_id),
            )
            conn.commit()
        raise
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="Import a zipped .prompts file into the prompt database.")
    parser.add_argument("zip_path", type=Path, help="Zip file containing one .prompts member")
    parser.add_argument("--member", help="Specific member inside the zip")
    parser.add_argument("--db", default=DEFAULT_DB_PATH, help="SQLite database path")
    parser.add_argument("--source-slug", default="kkwprompt", help="Identifier prefix for imported prompts")
    parser.add_argument("--batch-size", type=int, default=5000, help="Rows per commit")
    parser.add_argument("--limit", type=int, help="Stop after importing this many prompts")
    parser.add_argument("--dry-run", action="store_true", help="Parse and count without writing")
    args = parser.parse_args()

    result = import_zip(
        args.zip_path,
        member_name=args.member,
        db_path=args.db,
        source_slug=args.source_slug,
        batch_size=args.batch_size,
        limit=args.limit,
        dry_run=args.dry_run,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
