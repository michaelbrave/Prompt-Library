#!/usr/bin/env python3
"""Generate missing prompt style variants through an external LLM command."""

from __future__ import annotations

import argparse
import json
import shlex
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from prompt_library.db import DEFAULT_DB_PATH, get_connection
from prompt_library.wildcards import extract_wildcard_keys


TARGET_STYLES = {
    "everyday-speech": {
        "syntax_family": "everyday-speech",
        "negative_prompt_strategy": "minimal",
        "description": "Natural human-readable prompt prose. Keep it clear and concrete.",
    },
    "comma-separated": {
        "syntax_family": "comma-separated",
        "negative_prompt_strategy": "standard",
        "description": "Dense comma-separated image-generation prompt fragments.",
    },
    "booru-tags": {
        "syntax_family": "booru-tags",
        "negative_prompt_strategy": "standard",
        "description": "Danbooru-style tags with underscores, short tags, and comma separation.",
    },
    "enhanced-prompt": {
        "syntax_family": "enhanced-prompt",
        "negative_prompt_strategy": "weighted",
        "description": "Expanded high-detail prompt suitable for modern diffusion models.",
    },
    "lisp-like": {
        "syntax_family": "lisp-like",
        "negative_prompt_strategy": "structured",
        "description": "S-expression style structured prompt with nested visual fields.",
    },
    "structured-fields": {
        "syntax_family": "structured-fields",
        "negative_prompt_strategy": "structured",
        "description": "Field-labeled prompt with Subject, Environment, Lighting, Composition, Style, and Quality.",
    },
}

EXAMPLES = {
    "everyday-speech": {
        "positive_template": "A cinematic portrait of {person_subject} in {location_environment}, lit by {lighting}, with a {camera_angle} view and a {mood_atmosphere} mood.",
        "negative_template": "blurry, low quality, distorted anatomy",
    },
    "comma-separated": {
        "positive_template": "{person_subject}, {location_environment}, {lighting}, {camera_angle}, {mood_atmosphere}, {style_medium}, highly detailed",
        "negative_template": "blurry, low quality, bad anatomy, watermark",
    },
    "booru-tags": {
        "positive_template": "{person_subject}, {location_environment}, {lighting}, {camera_angle}, {mood_atmosphere}, {style_medium}, detailed_background",
        "negative_template": "lowres, blurry, bad_anatomy, watermark",
    },
    "enhanced-prompt": {
        "positive_template": "Highly detailed {style_medium} of {person_subject} in {location_environment}, {lighting}, {camera_angle}, layered atmospheric detail, coherent anatomy, strong composition, {mood_atmosphere}.",
        "negative_template": "low quality, blurry, bad anatomy, distorted hands, watermark, text artifacts",
    },
    "lisp-like": {
        "positive_template": "(prompt (subject \"{person_subject}\") (environment \"{location_environment}\") (lighting \"{lighting}\") (camera \"{camera_angle}\") (style \"{style_medium}\") (mood \"{mood_atmosphere}\"))",
        "negative_template": "(negative low-quality blurry bad-anatomy watermark)",
    },
    "structured-fields": {
        "positive_template": "Subject: {person_subject}\nEnvironment: {location_environment}\nLighting: {lighting}\nComposition: {camera_angle}\nStyle: {style_medium}\nMood: {mood_atmosphere}",
        "negative_template": "Avoid: blurry, low quality, bad anatomy, watermark",
    },
}


JOB_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS style_generation_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prompt_id INTEGER NOT NULL REFERENCES prompts(id),
    style_profile_id INTEGER NOT NULL REFERENCES prompt_style_profiles(id),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'running', 'completed', 'failed', 'skipped')),
    source_template_id INTEGER REFERENCES prompt_templates(id),
    task_payload TEXT NOT NULL DEFAULT '{}',
    response_payload TEXT,
    error_log TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at TEXT,
    UNIQUE(prompt_id, style_profile_id)
);
CREATE INDEX IF NOT EXISTS idx_style_generation_jobs_status ON style_generation_jobs(status);
CREATE INDEX IF NOT EXISTS idx_style_generation_jobs_prompt ON style_generation_jobs(prompt_id);
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fill missing prompt style variants using an external LLM.")
    parser.add_argument("--db", default=DEFAULT_DB_PATH, help="Path to SQLite database.")
    parser.add_argument("--prompt-set", help="Only process prompts in this prompt set, e.g. eval-core-100.")
    parser.add_argument("--style", action="append", choices=sorted(TARGET_STYLES), help="Target style to generate. Repeatable. Defaults to all target styles.")
    parser.add_argument("--limit", type=int, default=10, help="Maximum jobs to process this run.")
    parser.add_argument("--llm-cmd", help="Command that reads one JSON task from stdin and writes one JSON response to stdout.")
    parser.add_argument("--task-dir", type=Path, help="Write task JSON files here instead of calling an LLM.")
    parser.add_argument("--dry-run", action="store_true", help="Print selected missing jobs without writing templates.")
    parser.add_argument("--retry-failed", action="store_true", help="Retry failed jobs as well as pending jobs.")
    parser.add_argument("--allow-wildcard-drop", action="store_true", help="Allow generated positive templates to omit source wildcards.")
    parser.add_argument("--include-existing", action="store_true", help="Regenerate even when an enabled template already exists.")
    return parser.parse_args()


def ensure_schema(conn) -> None:
    conn.executescript(JOB_SCHEMA_SQL)
    conn.commit()


def ensure_style_profiles(conn, style_names: list[str], dry_run: bool) -> dict[str, int]:
    cursor = conn.cursor()
    style_ids = {}
    synthetic_id = -1
    for name in style_names:
        config = TARGET_STYLES[name]
        if not dry_run:
            cursor.execute(
                """
                INSERT OR IGNORE INTO prompt_style_profiles
                    (identifier, syntax_family, negative_prompt_strategy, ordering_notes, metadata, created_at)
                VALUES (?, ?, ?, ?, ?, datetime('now'))
                """,
                (
                    name,
                    config["syntax_family"],
                    config["negative_prompt_strategy"],
                    config["description"],
                    json.dumps({"managed_by": "tools/generate_missing_styles.py"}),
                ),
            )
        cursor.execute("SELECT id FROM prompt_style_profiles WHERE identifier = ?", (name,))
        row = cursor.fetchone()
        if row:
            style_ids[name] = row["id"]
        elif dry_run:
            style_ids[name] = synthetic_id
            synthetic_id -= 1
        else:
            raise RuntimeError(f"Failed to create style profile: {name}")
    if not dry_run:
        conn.commit()
    return style_ids


def prompt_scope_sql(prompt_set: str | None) -> tuple[str, list[str]]:
    if not prompt_set:
        return "p.status = 'active'", []
    return (
        """
        p.status = 'active'
        AND EXISTS (
            SELECT 1
            FROM prompt_set_members psm
            JOIN prompt_sets ps ON ps.id = psm.prompt_set_id
            WHERE psm.prompt_id = p.id
              AND psm.enabled = 1
              AND ps.name = ?
        )
        """,
        [prompt_set],
    )


def select_source_template(cursor, prompt_id: int, target_style_id: int):
    preferred = ["comma-separated", "kkwprompt-raw", "everyday-speech", "structured-fields", "enhanced-prompt", "lisp-like"]
    placeholders = ",".join("?" for _ in preferred)
    cursor.execute(
        f"""
        SELECT pt.id, psp.identifier AS style_identifier, pt.positive_template, pt.negative_template
        FROM prompt_templates pt
        JOIN prompt_style_profiles psp ON psp.id = pt.style_profile_id
        WHERE pt.prompt_id = ?
          AND pt.enabled = 1
          AND pt.style_profile_id != ?
        ORDER BY CASE psp.identifier
            {" ".join(f"WHEN ? THEN {index}" for index, _ in enumerate(preferred))}
            ELSE 100
        END, pt.id
        LIMIT 1
        """,
        [prompt_id, target_style_id, *preferred],
    )
    return cursor.fetchone()


def enabled_template_exists(cursor, prompt_id: int, style_id: int) -> bool:
    cursor.execute(
        "SELECT 1 FROM prompt_templates WHERE prompt_id = ? AND style_profile_id = ? AND enabled = 1",
        (prompt_id, style_id),
    )
    return cursor.fetchone() is not None


def job_status(cursor, prompt_id: int, style_id: int) -> str | None:
    try:
        cursor.execute(
            "SELECT status FROM style_generation_jobs WHERE prompt_id = ? AND style_profile_id = ?",
            (prompt_id, style_id),
        )
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc):
            return None
        raise
    row = cursor.fetchone()
    return row["status"] if row else None


def missing_jobs(
    conn,
    style_ids: dict[str, int],
    prompt_set: str | None,
    include_existing: bool,
    retry_failed: bool,
    limit: int,
):
    cursor = conn.cursor()
    scope_sql, params = prompt_scope_sql(prompt_set)
    cursor.execute(
        f"""
        SELECT p.id, p.identifier, p.concept, p.metadata
        FROM prompts p
        WHERE {scope_sql}
        ORDER BY p.id
        """,
        params,
    )
    prompts = cursor.fetchall()

    jobs = []
    for prompt in prompts:
        for style_name, style_id in style_ids.items():
            if not include_existing and enabled_template_exists(cursor, prompt["id"], style_id):
                continue
            status = job_status(cursor, prompt["id"], style_id)
            if status == "failed" and not retry_failed:
                continue
            if status in {"running", "completed", "skipped"}:
                continue
            source = select_source_template(cursor, prompt["id"], style_id)
            if source is None:
                continue
            jobs.append((prompt, style_name, style_id, source))
            if len(jobs) >= limit:
                return jobs
    return jobs


def build_task(prompt, style_name: str, source) -> dict:
    source_positive = source["positive_template"] or ""
    source_negative = source["negative_template"] or ""
    wildcard_keys = sorted(extract_wildcard_keys(source_positive) - {"concept"})
    style = TARGET_STYLES[style_name]
    return {
        "task": "rewrite_prompt_style_variant",
        "prompt_identifier": prompt["identifier"],
        "concept": prompt["concept"],
        "target_style": {
            "identifier": style_name,
            "syntax_family": style["syntax_family"],
            "negative_prompt_strategy": style["negative_prompt_strategy"],
            "description": style["description"],
        },
        "source_style": source["style_identifier"],
        "source_positive_template": source_positive,
        "source_negative_template": source_negative,
        "required_wildcards": wildcard_keys,
        "example": EXAMPLES[style_name],
        "output_contract": {
            "format": "json",
            "required_keys": ["positive_template", "negative_template", "notes"],
            "rules": [
                "Return only one JSON object and no markdown.",
                "Rewrite the prompt into the target style; do not translate the concept into a new scene.",
                "Preserve every required wildcard placeholder exactly, including braces.",
                "Do not invent new wildcard placeholders.",
                "Keep the positive template useful for image generation.",
                "Use an empty string for negative_template if the target style should not have one.",
            ],
        },
    }


def upsert_job(cursor, prompt_id: int, style_id: int, source_template_id: int, task: dict) -> int:
    cursor.execute(
        """
        INSERT INTO style_generation_jobs
            (prompt_id, style_profile_id, source_template_id, task_payload, status, updated_at)
        VALUES (?, ?, ?, ?, 'pending', datetime('now'))
        ON CONFLICT(prompt_id, style_profile_id) DO UPDATE SET
            source_template_id = excluded.source_template_id,
            task_payload = excluded.task_payload,
            updated_at = datetime('now')
        """,
        (prompt_id, style_id, source_template_id, json.dumps(task, sort_keys=True)),
    )
    cursor.execute(
        "SELECT id FROM style_generation_jobs WHERE prompt_id = ? AND style_profile_id = ?",
        (prompt_id, style_id),
    )
    return cursor.fetchone()["id"]


def call_llm(command: str, task: dict) -> dict:
    result = subprocess.run(
        shlex.split(command),
        input=json.dumps(task, indent=2),
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"LLM command exited {result.returncode}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError(f"LLM output was not valid JSON: {exc}: {result.stdout[:500]}") from exc


def validate_response(response: dict, required_wildcards: list[str], allow_wildcard_drop: bool) -> None:
    for key in ["positive_template", "negative_template", "notes"]:
        if key not in response:
            raise ValueError(f"Missing response key: {key}")
        if not isinstance(response[key], str):
            raise ValueError(f"Response key must be a string: {key}")

    positive_keys = extract_wildcard_keys(response["positive_template"]) - {"concept"}
    negative_keys = extract_wildcard_keys(response["negative_template"]) - {"concept"}
    required = set(required_wildcards)
    extras = (positive_keys | negative_keys) - required
    if extras:
        raise ValueError(f"Generated template introduced unbound wildcards: {sorted(extras)}")
    if not allow_wildcard_drop:
        missing = required - positive_keys
        if missing:
            raise ValueError(f"Generated positive template omitted required wildcards: {sorted(missing)}")


def upsert_template(cursor, prompt_id: int, style_id: int, response: dict) -> None:
    positive = response["positive_template"]
    negative = response["negative_template"]
    notes = response["notes"]
    cursor.execute(
        """
        SELECT id, positive_template, negative_template, notes
        FROM prompt_templates
        WHERE prompt_id = ? AND style_profile_id = ?
        """,
        (prompt_id, style_id),
    )
    existing = cursor.fetchone()
    if existing:
        cursor.execute(
            """
            UPDATE prompt_templates
            SET positive_template = ?, negative_template = ?, notes = ?, enabled = 1, updated_at = datetime('now')
            WHERE id = ?
            """,
            (positive, negative, notes, existing["id"]),
        )
        template_id = existing["id"]
        change_type = "updated"
    else:
        cursor.execute(
            """
            INSERT INTO prompt_templates
                (prompt_id, style_profile_id, positive_template, negative_template, enabled, notes, created_at, updated_at)
            VALUES (?, ?, ?, ?, 1, ?, datetime('now'), datetime('now'))
            """,
            (prompt_id, style_id, positive, negative, notes),
        )
        template_id = cursor.lastrowid
        change_type = "created"

    cursor.execute("SELECT COALESCE(MAX(version), 0) + 1 FROM prompt_template_versions WHERE template_id = ?", (template_id,))
    version = cursor.fetchone()[0]
    cursor.execute(
        """
        INSERT INTO prompt_template_versions
            (template_id, version, positive_template, negative_template, change_type, changed_by, change_reason, created_at)
        VALUES (?, ?, ?, ?, ?, 'llm-style-generator', 'Generated missing style variant', datetime('now'))
        """,
        (template_id, version, positive, negative, change_type),
    )


def mark_job(cursor, job_id: int, status: str, response: dict | None = None, error: str | None = None) -> None:
    cursor.execute(
        """
        UPDATE style_generation_jobs
        SET status = ?,
            response_payload = COALESCE(?, response_payload),
            error_log = ?,
            attempt_count = attempt_count + CASE WHEN ? = 'running' THEN 1 ELSE 0 END,
            updated_at = datetime('now'),
            completed_at = CASE WHEN ? = 'completed' THEN datetime('now') ELSE completed_at END
        WHERE id = ?
        """,
        (
            status,
            json.dumps(response, sort_keys=True) if response is not None else None,
            error,
            status,
            status,
            job_id,
        ),
    )


def write_task_file(task_dir: Path, prompt_identifier: str, style_name: str, task: dict) -> Path:
    task_dir.mkdir(parents=True, exist_ok=True)
    path = task_dir / f"{prompt_identifier}__{style_name}.json"
    path.write_text(json.dumps(task, indent=2, sort_keys=True), encoding="utf-8")
    return path


def main() -> None:
    args = parse_args()
    if args.limit <= 0:
        raise SystemExit("--limit must be positive")
    if not args.dry_run and not args.task_dir and not args.llm_cmd:
        raise SystemExit("Provide --llm-cmd, --task-dir, or --dry-run")

    style_names = args.style or list(TARGET_STYLES)
    conn = get_connection(args.db)
    if not args.dry_run:
        ensure_schema(conn)
    style_ids = ensure_style_profiles(conn, style_names, args.dry_run)
    jobs = missing_jobs(conn, style_ids, args.prompt_set, args.include_existing, args.retry_failed, args.limit)

    cursor = conn.cursor()
    processed = 0
    for prompt, style_name, style_id, source in jobs:
        task = build_task(prompt, style_name, source)

        label = f"{prompt['identifier']} -> {style_name}"
        if args.dry_run:
            print(label)
            continue
        job_id = upsert_job(cursor, prompt["id"], style_id, source["id"], task)
        conn.commit()
        if args.task_dir:
            path = write_task_file(args.task_dir, prompt["identifier"], style_name, task)
            print(f"Wrote task {path}")
            processed += 1
            continue

        try:
            mark_job(cursor, job_id, "running")
            conn.commit()
            response = call_llm(args.llm_cmd, task)
            validate_response(response, task["required_wildcards"], args.allow_wildcard_drop)
            upsert_template(cursor, prompt["id"], style_id, response)
            mark_job(cursor, job_id, "completed", response=response)
            conn.commit()
            print(f"Completed {label}")
            processed += 1
        except Exception as exc:
            mark_job(cursor, job_id, "failed", error=str(exc))
            conn.commit()
            print(f"Failed {label}: {exc}", file=sys.stderr)

    if not jobs:
        print("No missing style variants found for the selected scope.")
    else:
        print(f"Selected {len(jobs)} jobs; processed {processed}.")


if __name__ == "__main__":
    main()
