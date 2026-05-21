#!/usr/bin/env python3
"""Retrofit prompt templates: replace literal wildcard values with {key} syntax and create bindings.

Conservative approach:
- Never replace style_negative values in positive templates (they belong in negatives only)
- Only replace multi-word values (single words are too ambiguous)
- Longest match wins, no overlapping replacements
"""

import sqlite3
import re
from collections import defaultdict


DB_PATH = "data/prompts.db"

# Categories that should only be replaced in negative templates
NEGATIVE_ONLY_CATEGORIES = {"style_negative"}


def load_wildcards(conn):
    """Load all wildcard values grouped by key."""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT wd.wildcard_key, wv.value
        FROM wildcard_values wv
        JOIN wildcard_definitions wd ON wv.wildcard_definition_id = wd.id
        WHERE wd.status = 'active'
        ORDER BY wd.wildcard_key
    """)

    wildcards = defaultdict(list)
    for row in cursor.fetchall():
        wildcards[row["wildcard_key"]].append(row["value"])

    return wildcards


def build_replacement_patterns(wildcards, for_negative=False):
    """Build regex pattern and replacement map for wildcard values.

    Only includes multi-word values to avoid ambiguous single-word matches.
    For positive templates, excludes style_negative category.
    """
    all_values = []
    for key, values in wildcards.items():
        # Skip negative-only categories in positive templates
        if not for_negative and key in NEGATIVE_ONLY_CATEGORIES:
            continue
        for value in values:
            # Only use multi-word values (contain space or hyphen)
            if " " in value or "-" in value:
                all_values.append((value, key))

    # Sort by length descending so longest matches win
    all_values.sort(key=lambda x: len(x[0]), reverse=True)

    # Build regex pattern with word boundaries
    escaped = [re.escape(val) for val, _ in all_values]
    if not escaped:
        return None, {}

    pattern_str = "|".join(f"(?:{val})" for val in escaped)
    pattern = re.compile(r"\b(?:" + pattern_str + r")\b", re.IGNORECASE)

    # Build lookup: lowercase value -> key
    value_to_key = {}
    for val, key in all_values:
        value_to_key[val.lower()] = key

    return pattern, value_to_key


def retrofit_template(text, pattern, value_to_key):
    """Replace literal wildcard values in text with {key} syntax.

    Uses non-overlapping longest-match-first approach.
    Collapses adjacent identical wildcards into one.
    Returns (new_text, set_of_keys_used).
    """
    if not pattern:
        return text, set()

    keys_found = set()

    # Find all matches
    matches = list(pattern.finditer(text))
    if not matches:
        return text, set()

    # Sort by start position, then by length (longest first) for overlapping
    matches.sort(key=lambda m: (m.start(), -len(m.group(0))))

    # Remove overlapping matches (keep longest at each position)
    filtered = []
    last_end = 0
    for match in matches:
        if match.start() >= last_end:
            filtered.append(match)
            last_end = match.end()

    # Build new text with replacements, collapsing adjacent identical wildcards
    parts = []
    prev_end = 0
    last_key = None
    for match in filtered:
        # Skip whitespace between matches
        between = text[prev_end:match.start()]
        stripped_between = between.strip()

        matched = match.group(0)
        key = value_to_key.get(matched.lower())
        if not key:
            parts.append(between)
            parts.append(matched)
            prev_end = match.end()
            continue

        # If adjacent to previous wildcard of same key, skip this one
        if key == last_key and not stripped_between:
            prev_end = match.end()
            continue

        keys_found.add(key)
        parts.append(between)
        parts.append("{" + key + "}")
        last_key = key
        prev_end = match.end()
    parts.append(text[prev_end:])

    return "".join(parts), keys_found


def main(dry_run=False, batch_size=5000, sample_size=5):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    wildcards = load_wildcards(conn)
    pos_pattern, pos_map = build_replacement_patterns(wildcards, for_negative=False)
    neg_pattern, neg_map = build_replacement_patterns(wildcards, for_negative=True)

    total_values = sum(len(v) for v in wildcards.values())
    multi_word = sum(1 for vals in wildcards.values() for v in vals if " " in v or "-" in v)
    print(f"Loaded {len(wildcards)} wildcard categories with {total_values} total values ({multi_word} multi-word)")
    if dry_run:
        print("DRY RUN - no changes will be made")
    print()

    # Get all templates
    read_cursor = conn.cursor()
    write_cursor = conn.cursor()
    read_cursor.execute("SELECT COUNT(*) FROM prompt_templates WHERE enabled = 1")
    template_count = read_cursor.fetchone()[0]
    read_cursor.execute("""
        SELECT pt.id, pt.prompt_id, pt.positive_template, pt.negative_template,
               p.identifier as prompt_identifier, psp.identifier as style_identifier
        FROM prompt_templates pt
        JOIN prompts p ON pt.prompt_id = p.id
        JOIN prompt_style_profiles psp ON pt.style_profile_id = psp.id
        WHERE pt.enabled = 1
        ORDER BY p.identifier, psp.identifier
    """)

    templates = read_cursor
    print(f"Processing {template_count} templates...")
    print()

    prompt_keys = defaultdict(set)
    samples = []
    modified_templates = 0
    processed_templates = 0

    for tmpl in templates:
        processed_templates += 1
        pos_text = tmpl["positive_template"]
        neg_text = tmpl["negative_template"] or ""

        new_pos, pos_keys = retrofit_template(pos_text, pos_pattern, pos_map)
        new_neg, neg_keys = retrofit_template(neg_text, neg_pattern, neg_map)

        all_keys = pos_keys | neg_keys

        changed = new_pos != pos_text or new_neg != neg_text

        if changed:
            modified_templates += 1
            prompt_keys[tmpl["prompt_id"]].update(all_keys)
            if len(samples) < sample_size:
                samples.append({
                    "prompt": tmpl["prompt_identifier"],
                    "style": tmpl["style_identifier"],
                    "keys": sorted(all_keys),
                    "old_pos": pos_text[:150],
                    "new_pos": new_pos[:150],
                    "old_neg": neg_text[:100],
                    "new_neg": new_neg[:100],
                })

            if not dry_run:
                write_cursor.execute(
                    "UPDATE prompt_templates SET positive_template = ?, negative_template = ?, updated_at = datetime('now') WHERE id = ?",
                    (new_pos, new_neg, tmpl["id"]),
                )
                if modified_templates % batch_size == 0:
                    conn.commit()

        if processed_templates % 100000 == 0:
            print(f"Processed {processed_templates} templates; modified {modified_templates}...")

    if not dry_run:
        conn.commit()

    # Create wildcard bindings for prompts that had changes
    bindings_created = 0
    for prompt_db_id, keys in prompt_keys.items():
        for key in keys:
            write_cursor.execute("SELECT id FROM wildcard_definitions WHERE wildcard_key = ?", (key,))
            wd_row = write_cursor.fetchone()
            if not wd_row:
                continue
            wd_id = wd_row["id"]

            write_cursor.execute(
                "SELECT id FROM prompt_wildcard_bindings WHERE prompt_id = ? AND wildcard_definition_id = ?",
                (prompt_db_id, wd_id),
            )
            existing = write_cursor.fetchone()
            if not existing:
                if not dry_run:
                    write_cursor.execute(
                        "INSERT INTO prompt_wildcard_bindings (prompt_id, wildcard_definition_id, required, default_strategy) VALUES (?, ?, 0, 'random')",
                        (prompt_db_id, wd_id),
                    )
                bindings_created += 1

    if not dry_run:
        conn.commit()

    # Report
    verb = "would be" if dry_run else "were"
    print(f"Templates that {verb} modified: {modified_templates}")
    print(f"Prompts that {verb} bound: {len(prompt_keys)}")
    print(f"Bindings that {verb} created: {bindings_created}")
    print()

    # Show sample changes
    for sample in samples:
        print(f"=== {sample['prompt']} ===")
        print(f"  Style: {sample['style']}")
        print(f"  Keys found: {sample['keys']}")
        if sample["old_pos"] != sample["new_pos"]:
            print(f"  OLD: {sample['old_pos']}...")
            print(f"  NEW: {sample['new_pos']}...")
        if sample["old_neg"] != sample["new_neg"] and sample["old_neg"]:
            print(f"  NEG OLD: {sample['old_neg']}...")
            print(f"  NEG NEW: {sample['new_neg']}...")
        print()

    conn.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Replace literal wildcard values in templates with {key} placeholders."
    )
    parser.add_argument("--apply", action="store_true", help="Write template and binding changes to the database")
    parser.add_argument("--batch-size", type=int, default=5000, help="Updated templates per commit")
    parser.add_argument("--sample-size", type=int, default=5, help="Number of sample changes to print")
    args = parser.parse_args()
    main(dry_run=not args.apply, batch_size=args.batch_size, sample_size=args.sample_size)
