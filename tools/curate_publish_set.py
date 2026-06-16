#!/usr/bin/env python3
"""Curate a high-quality, diverse prompt set for style generation and publishing.

This script does not delete prompts. By default it only prints a summary and
writes a report. Use --write to create/update prompt_sets and prompt metadata.
"""

from __future__ import annotations

import argparse
import heapq
import json
import math
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from prompt_library.db import DEFAULT_DB_PATH, get_connection
from prompt_library.wildcards import extract_wildcard_keys

DEFAULT_REPORT = ROOT / "docs" / "curated-style-set-1000.md"

TARGET_STYLE_SOURCE_ORDER = [
    "comma-separated",
    "kkwprompt-raw",
    "everyday-speech",
    "enhanced-prompt",
    "structured-fields",
    "lisp-like",
]

DOMAINS = [
    "photography",
    "anime-cartoon",
    "illustration-painting",
    "cgi-render",
    "design-product",
    "environment-world",
    "mixed-general",
]

DOMAIN_KEYWORDS = {
    "photography": {
        "photo", "photograph", "photographic", "photorealistic", "realistic", "dslr",
        "35mm", "50mm", "85mm", "lens", "bokeh", "film grain", "studio", "cinematic still",
        "portrait photography", "street photography", "macro photography",
    },
    "anime-cartoon": {
        "anime", "manga", "cartoon", "comic", "chibi", "cel shading", "toon", "pixiv",
        "danbooru", "1girl", "1boy", "kawaii", "line art", "character sheet",
    },
    "illustration-painting": {
        "illustration", "painting", "oil painting", "watercolor", "gouache", "ink", "sketch",
        "concept art", "digital art", "fine art", "brush", "canvas", "matte painting", "artstation",
    },
    "cgi-render": {
        "3d", "cgi", "render", "octane", "unreal engine", "blender", "cinema 4d",
        "ray tracing", "rtx", "isometric", "low poly", "unity", "vfx",
    },
    "design-product": {
        "product", "packaging", "logo", "poster", "typography", "interface", "ui", "fashion",
        "shoe", "watch", "furniture", "vehicle", "car", "industrial design", "advertising",
    },
    "environment-world": {
        "landscape", "environment", "forest", "desert", "ocean", "mountain", "city", "street",
        "architecture", "interior", "building", "room", "castle", "spaceship", "planet", "world",
    },
}

TAG_KEYWORDS = {
    "portrait": {"portrait", "headshot", "face", "person", "woman", "man", "girl", "boy"},
    "character": {"character", "hero", "warrior", "mage", "creature", "monster", "robot"},
    "landscape": {"landscape", "mountain", "forest", "desert", "ocean", "valley", "river"},
    "architecture": {"architecture", "building", "interior", "room", "city", "street", "house"},
    "product": {"product", "packaging", "shoe", "watch", "furniture", "vehicle", "car"},
    "lighting": {"lighting", "light", "shadow", "glow", "rim light", "golden hour", "volumetric"},
    "composition": {"composition", "close up", "wide angle", "full body", "top down", "macro"},
    "motion": {"motion", "running", "jumping", "flying", "dance", "action", "dynamic"},
    "materials": {"glass", "metal", "fabric", "water", "skin", "hair", "fur", "leather"},
    "text-design": {"sign", "logo", "typography", "lettering", "poster", "label"},
}

GENERIC_QUALITY_TERMS = {
    "best quality", "high quality", "masterpiece", "highres", "ultra detailed", "highly detailed",
    "detailed", "intricate", "beautiful", "amazing", "award winning", "trending on artstation",
    "8k", "4k", "32k", "hd", "hdr", "uhd",
}

BAD_FRAGMENT_TERMS = {
    "prompt:", "negative prompt:", "stable diffusion", "midjourney prompt", "click here",
    "http://", "https://", "www.", "seed:", "steps:", "sampler:", "cfg scale:",
}

NSFW_TERMS = {
    "nsfw", "nude", "naked", "nipples", "pussy", "sex", "erotic", "explicit", "porn",
}

STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in", "into", "is",
    "it", "its", "of", "on", "or", "that", "the", "this", "to", "with", "without",
}

TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_-]*")


@dataclass(order=True)
class Candidate:
    sort_score: float
    prompt_id: int = field(compare=False)
    identifier: str = field(compare=False)
    concept: str = field(compare=False)
    source_style: str = field(compare=False)
    source_template_id: int = field(compare=False)
    positive_template: str = field(compare=False)
    negative_template: str = field(compare=False)
    metadata: dict = field(compare=False)
    domain: str = field(compare=False)
    tags: list[str] = field(compare=False)
    wildcard_keys: list[str] = field(compare=False)
    quality_terms: list[str] = field(compare=False)
    score: float = field(compare=False)
    reasons: list[str] = field(compare=False)
    signature: frozenset[str] = field(compare=False)


def tokenize(text: str) -> list[str]:
    return TOKEN_RE.findall(text.lower())


def phrase_hits(text: str, phrases: set[str]) -> list[str]:
    lowered = text.lower()
    return sorted([phrase for phrase in phrases if phrase in lowered])


def classify_domain(text: str) -> str:
    scored = {name: len(phrase_hits(text, terms)) for name, terms in DOMAIN_KEYWORDS.items()}
    domain, score = max(scored.items(), key=lambda item: item[1])
    return domain if score > 0 else "mixed-general"


def classify_tags(text: str) -> list[str]:
    tags = [name for name, terms in TAG_KEYWORDS.items() if phrase_hits(text, terms)]
    return tags[:8]


def length_score(word_count: int) -> float:
    if word_count < 8:
        return -12.0
    if 18 <= word_count <= 85:
        return 14.0
    if word_count < 18:
        return 4.0 + (word_count - 8) * 0.8
    return max(0.0, 14.0 - ((word_count - 85) / 10.0))


def duplicate_signature(text: str) -> frozenset[str]:
    lowered = text.lower()
    for term in GENERIC_QUALITY_TERMS:
        lowered = lowered.replace(term, " ")
    tokens = [t for t in tokenize(lowered) if len(t) > 2 and t not in STOPWORDS]
    return frozenset(tokens[:120])


def jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def safe_metadata(raw: str | None) -> dict:
    try:
        return json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {"metadata_parse_error": True}


def score_row(row, min_wildcards: int, include_nsfw: bool) -> Candidate | None:
    positive = row["positive_template"] or ""
    negative = row["negative_template"] or ""
    concept = row["concept"] or ""
    text = f"{concept} {positive}"
    lowered = text.lower()

    if not include_nsfw and any(term in lowered for term in NSFW_TERMS):
        return None
    if any(term in lowered for term in BAD_FRAGMENT_TERMS):
        return None
    if positive.count("{") != positive.count("}"):
        return None

    tokens = tokenize(text)
    unique = set(tokens)
    if len(tokens) < 8 or len(unique) < 6:
        return None

    wildcard_keys = sorted(extract_wildcard_keys(positive) - {"concept"})
    if len(wildcard_keys) < min_wildcards:
        return None

    domain = classify_domain(text)
    tags = classify_tags(text)
    quality_terms = phrase_hits(text, GENERIC_QUALITY_TERMS)
    domain_hits = len(phrase_hits(text, set().union(*DOMAIN_KEYWORDS.values())))
    visual_hits = len(tags) + domain_hits

    source_bonus = 0.0
    if row["source_style"] == "comma-separated":
        source_bonus = 3.0
    elif row["source_style"] in {"everyday-speech", "kkwprompt-raw"}:
        source_bonus = 2.0

    score = (
        length_score(len(tokens))
        + min(len(wildcard_keys), 8) * 5.0
        + min(len(tags), 7) * 3.0
        + min(visual_hits, 12) * 1.7
        + math.log1p(len(unique - STOPWORDS)) * 3.0
        + source_bonus
        - min(len(quality_terms), 8) * 0.9
    )

    if len(wildcard_keys) >= 3:
        score += 8.0
    if domain != "mixed-general":
        score += 3.0
    if score < 30.0:
        return None

    reasons = [
        f"{domain}",
        f"{len(wildcard_keys)} wildcards",
        f"{len(tags)} tags",
    ]
    if quality_terms:
        reasons.append("quality terms: " + ", ".join(quality_terms[:4]))

    return Candidate(
        sort_score=score,
        prompt_id=row["id"],
        identifier=row["identifier"],
        concept=concept,
        source_style=row["source_style"],
        source_template_id=row["template_id"],
        positive_template=positive,
        negative_template=negative,
        metadata=safe_metadata(row["metadata"]),
        domain=domain,
        tags=tags,
        wildcard_keys=wildcard_keys,
        quality_terms=quality_terms,
        score=score,
        reasons=reasons,
        signature=duplicate_signature(text),
    )


def iter_prompt_rows(conn, max_scan: int | None):
    placeholders = ",".join("?" for _ in TARGET_STYLE_SOURCE_ORDER)
    order_cases = " ".join(
        f"WHEN ? THEN {index}" for index, _ in enumerate(TARGET_STYLE_SOURCE_ORDER)
    )
    sql = f"""
        SELECT p.id, p.identifier, p.concept, p.metadata,
               pt.id AS template_id,
               psp.identifier AS source_style,
               pt.positive_template, pt.negative_template
        FROM prompts p
        JOIN prompt_templates pt ON pt.prompt_id = p.id AND pt.enabled = 1
        JOIN prompt_style_profiles psp ON psp.id = pt.style_profile_id
        WHERE p.status = 'active'
          AND psp.identifier IN ({placeholders})
        ORDER BY p.id,
            CASE psp.identifier {order_cases} ELSE 100 END,
            pt.id
    """
    params = [*TARGET_STYLE_SOURCE_ORDER, *TARGET_STYLE_SOURCE_ORDER]
    seen: set[int] = set()
    count = 0
    for row in conn.execute(sql, params):
        if row["id"] in seen:
            continue
        seen.add(row["id"])
        count += 1
        if max_scan is not None and count > max_scan:
            break
        yield row


def load_candidates(conn, args) -> list[Candidate]:
    heaps: dict[str, list[Candidate]] = {domain: [] for domain in DOMAINS}
    scanned = 0
    kept = 0
    for row in iter_prompt_rows(conn, None if args.max_scan == 0 else args.max_scan):
        scanned += 1
        candidate = score_row(row, args.min_wildcards, args.include_nsfw)
        if candidate is None:
            continue
        heap = heaps.setdefault(candidate.domain, [])
        if len(heap) < args.pool_size_per_domain:
            heapq.heappush(heap, candidate)
            kept += 1
        elif candidate.score > heap[0].score:
            heapq.heapreplace(heap, candidate)

    candidates = sorted(
        [candidate for heap in heaps.values() for candidate in heap],
        key=lambda c: c.score,
        reverse=True,
    )
    print(f"Scanned {scanned} prompts; retained {len(candidates)} candidates across domain pools.")
    for domain in DOMAINS:
        print(f"  pool {domain}: {len(heaps.get(domain, []))}")
    return candidates


def quotas(target: int) -> dict[str, int]:
    base = target // len(DOMAINS)
    remainder = target % len(DOMAINS)
    return {domain: base + (1 if i < remainder else 0) for i, domain in enumerate(DOMAINS)}


def choose_diverse(candidates: list[Candidate], target: int, threshold: float) -> tuple[list[Candidate], list[Candidate]]:
    selected: list[Candidate] = []
    rejected_similar: list[Candidate] = []
    used_ids: set[int] = set()
    tag_counts: dict[str, int] = {}

    by_domain: dict[str, list[Candidate]] = {domain: [] for domain in DOMAINS}
    for c in candidates:
        by_domain.setdefault(c.domain, []).append(c)

    def is_similar(candidate: Candidate, existing: list[Candidate], local_threshold: float) -> bool:
        return any(jaccard(candidate.signature, chosen.signature) >= local_threshold for chosen in existing)

    def try_add(candidate: Candidate, local_threshold: float, strict_tags: bool) -> bool:
        if candidate.prompt_id in used_ids:
            return False
        if is_similar(candidate, selected, local_threshold):
            rejected_similar.append(candidate)
            return False
        if strict_tags and candidate.tags:
            tag_limit = max(30, target // 7)
            if max(tag_counts.get(tag, 0) for tag in candidate.tags) >= tag_limit:
                return False
        selected.append(candidate)
        used_ids.add(candidate.prompt_id)
        for tag in candidate.tags:
            tag_counts[tag] = tag_counts.get(tag, 0) + 1
        return True

    # First satisfy domain quotas with a relaxed duplicate threshold. This keeps
    # the publish set broad instead of letting one high-scoring domain dominate.
    quota_threshold = min(0.9, threshold + 0.18)
    for domain, quota in quotas(target).items():
        domain_selected = 0
        for candidate in by_domain.get(domain, []):
            if domain_selected >= quota:
                break
            if try_add(candidate, quota_threshold, strict_tags=False):
                domain_selected += 1

    # Fill any remaining slots using the normal stricter diversity rule.
    for candidate in candidates:
        if len(selected) >= target:
            break
        try_add(candidate, threshold, strict_tags=True)

    # Last resort: still avoid exact-ish duplicates, but prioritize reaching the target.
    if len(selected) < target:
        fallback_threshold = min(0.94, threshold + 0.22)
        for candidate in candidates:
            if len(selected) >= target:
                break
            try_add(candidate, fallback_threshold, strict_tags=False)

    return selected[:target], rejected_similar


def upsert_prompt_set(cursor, name: str, description: str, tags: list[str], metadata: dict, candidates: list[Candidate]) -> None:
    cursor.execute(
        """
        INSERT INTO prompt_sets (name, description, status, tags, metadata, created_at)
        VALUES (?, ?, 'active', ?, ?, datetime('now'))
        ON CONFLICT(name) DO UPDATE SET
            description = excluded.description,
            status = excluded.status,
            tags = excluded.tags,
            metadata = excluded.metadata
        """,
        (name, description, json.dumps(tags), json.dumps(metadata, sort_keys=True)),
    )
    cursor.execute("SELECT id FROM prompt_sets WHERE name = ?", (name,))
    set_id = cursor.fetchone()["id"]
    cursor.execute("DELETE FROM prompt_set_members WHERE prompt_set_id = ?", (set_id,))
    for pos, candidate in enumerate(candidates, start=1):
        cursor.execute(
            "INSERT INTO prompt_set_members (prompt_set_id, prompt_id, position, enabled) VALUES (?, ?, ?, 1)",
            (set_id, candidate.prompt_id, pos),
        )


def update_candidate_metadata(cursor, candidate: Candidate, set_name: str, position: int) -> None:
    metadata = dict(candidate.metadata)
    metadata["publish_curation"] = {
        "set": set_name,
        "position": position,
        "score": round(candidate.score, 2),
        "domain": candidate.domain,
        "tags": candidate.tags,
        "wildcard_keys": candidate.wildcard_keys,
        "quality_terms_to_wildcard": candidate.quality_terms,
        "source_style": candidate.source_style,
    }
    cursor.execute(
        "UPDATE prompts SET metadata = ?, updated_at = datetime('now') WHERE id = ?",
        (json.dumps(metadata, sort_keys=True), candidate.prompt_id),
    )


def ensure_quality_wildcard(cursor, key: str, selected: list[Candidate]) -> int | None:
    values = sorted({term for c in selected for term in c.quality_terms})
    if not values:
        return None
    cursor.execute(
        """
        INSERT OR IGNORE INTO wildcard_definitions (wildcard_key, status, notes, metadata, created_at, updated_at)
        VALUES (?, 'active', ?, ?, datetime('now'), datetime('now'))
        """,
        (
            key,
            "Generic quality modifiers extracted during publish-set curation.",
            json.dumps({"managed_by": "tools/curate_publish_set.py"}, sort_keys=True),
        ),
    )
    cursor.execute("SELECT id FROM wildcard_definitions WHERE wildcard_key = ?", (key,))
    wildcard_id = cursor.fetchone()["id"]
    for value in values:
        cursor.execute(
            "INSERT OR IGNORE INTO wildcard_values (wildcard_definition_id, value, weight, created_at) VALUES (?, ?, 1.0, datetime('now'))",
            (wildcard_id, value),
        )



def normalize_quality_terms(text: str, wildcard_key: str) -> str:
    if not wildcard_key:
        return text
    replacement = "{" + wildcard_key + "}"
    terms = sorted(GENERIC_QUALITY_TERMS, key=len, reverse=True)
    pattern = re.compile(r"(?<![A-Za-z0-9_])(" + "|".join(re.escape(term) for term in terms) + r")(?![A-Za-z0-9_])", re.IGNORECASE)
    updated = pattern.sub(replacement, text)
    updated = re.sub(rf"(?:{re.escape(replacement)}\s*,\s*)+{re.escape(replacement)}", replacement, updated)
    updated = re.sub(rf"{re.escape(replacement)}(?:\s+{re.escape(replacement)})+", replacement, updated)
    updated = re.sub(r"\s+,", ",", updated)
    updated = re.sub(r",\s*,+", ",", updated)
    updated = re.sub(r"\s{2,}", " ", updated)
    return updated.strip(" ,")


def rewrite_selected_quality_terms(cursor, selected: list[Candidate], wildcard_key: str) -> int:
    changed = 0
    for candidate in selected:
        updated = normalize_quality_terms(candidate.positive_template, wildcard_key)
        if updated == candidate.positive_template:
            continue
        cursor.execute(
            """
            UPDATE prompt_templates
            SET positive_template = ?, updated_at = datetime('now')
            WHERE id = ?
            """,
            (updated, candidate.source_template_id),
        )
        cursor.execute("SELECT COALESCE(MAX(version), 0) + 1 FROM prompt_template_versions WHERE template_id = ?", (candidate.source_template_id,))
        version = cursor.fetchone()[0]
        cursor.execute(
            """
            INSERT INTO prompt_template_versions
                (template_id, version, positive_template, negative_template, change_type, changed_by, change_reason, created_at)
            VALUES (?, ?, ?, ?, 'updated', 'curate-publish-set', ?, datetime('now'))
            """,
            (
                candidate.source_template_id,
                version,
                updated,
                candidate.negative_template,
                f"Moved generic quality terms into {{{wildcard_key}}}",
            ),
        )
        candidate.positive_template = updated
        candidate.wildcard_keys = sorted(extract_wildcard_keys(updated) - {"concept"})
        changed += 1
    return changed

def write_database(conn, args, candidates: list[Candidate], selected: list[Candidate], rejected_similar: list[Candidate]) -> None:
    cursor = conn.cursor()
    metadata = {
        "builder": "tools/curate_publish_set.py",
        "target": args.target,
        "similarity_threshold": args.similarity_threshold,
        "min_wildcards": args.min_wildcards,
    }
    if args.candidate_set:
        upsert_prompt_set(
            cursor,
            args.candidate_set,
            "Larger high-scoring candidate pool retained for future publish supersets and review.",
            ["publish", "candidate-pool", "curated", "review"],
            {**metadata, "candidate_count": len(candidates)},
            candidates[: args.candidate_limit],
        )

    if args.clean_quality_terms and args.quality_wildcard_key:
        rewritten = rewrite_selected_quality_terms(cursor, selected, args.quality_wildcard_key)
        metadata["quality_templates_rewritten"] = rewritten

    upsert_prompt_set(
        cursor,
        args.set_name,
        "Curated high-quality, diverse wildcard prompt set for style generation and publishing.",
        ["publish", "curated", "style-generation", "wildcards"],
        metadata,
        selected,
    )
    for pos, candidate in enumerate(selected, start=1):
        update_candidate_metadata(cursor, candidate, args.set_name, pos)

    if args.duplicates_set and rejected_similar:
        upsert_prompt_set(
            cursor,
            args.duplicates_set,
            "Near-duplicate prompts rejected while building the curated publish set.",
            ["publish", "dedupe", "review"],
            {**metadata, "source_set": args.set_name},
            rejected_similar[: args.duplicates_limit],
        )

    if args.quality_wildcard_key:
        wildcard_id = ensure_quality_wildcard(cursor, args.quality_wildcard_key, selected)
        metadata["quality_bindings_added"] = bind_quality_wildcard(cursor, wildcard_id, selected, args.quality_wildcard_key)

    conn.commit()


def write_report(path: Path, selected: list[Candidate], rejected_similar: list[Candidate], args) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    domain_counts: dict[str, int] = {}
    tag_counts: dict[str, int] = {}
    wildcard_counts: dict[str, int] = {}
    quality_counts: dict[str, int] = {}
    for c in selected:
        domain_counts[c.domain] = domain_counts.get(c.domain, 0) + 1
        for tag in c.tags:
            tag_counts[tag] = tag_counts.get(tag, 0) + 1
        for key in c.wildcard_keys:
            wildcard_counts[key] = wildcard_counts.get(key, 0) + 1
        for term in c.quality_terms:
            quality_counts[term] = quality_counts.get(term, 0) + 1

    lines = [
        "# Curated Style Publish Set",
        "",
        f"Set name: `{args.set_name}`",
        f"Selected prompts: {len(selected)}",
        f"Near-duplicate candidates rejected during selection: {len(rejected_similar)}",
        f"Dry run: {not args.write}",
        "",
        "## Coverage",
        "",
        "### Domains",
        "",
    ]
    for key, count in sorted(domain_counts.items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"- {key}: {count}")
    lines.extend(["", "### Tags", ""])
    for key, count in sorted(tag_counts.items(), key=lambda item: (-item[1], item[0]))[:30]:
        lines.append(f"- {key}: {count}")
    lines.extend(["", "### Wildcards", ""])
    for key, count in sorted(wildcard_counts.items(), key=lambda item: (-item[1], item[0]))[:40]:
        lines.append(f"- `{key}`: {count}")
    lines.extend(["", "### Generic Quality Terms To Convert To Wildcards", ""])
    if quality_counts:
        for key, count in sorted(quality_counts.items(), key=lambda item: (-item[1], item[0])):
            lines.append(f"- `{key}`: {count}")
    else:
        lines.append("- none")

    lines.extend([
        "",
        "## Selected Prompts",
        "",
        "| # | Identifier | Domain | Score | Source | Wildcards | Tags | Reason |",
        "|---:|---|---|---:|---|---|---|---|",
    ])
    for idx, c in enumerate(selected, start=1):
        wildcards = ", ".join(c.wildcard_keys) or "-"
        tags = ", ".join(c.tags) or "-"
        reason = "; ".join(c.reasons).replace("|", "/")
        lines.append(
            f"| {idx} | `{c.identifier}` | {c.domain} | {c.score:.2f} | {c.source_style} | {wildcards} | {tags} | {reason} |"
        )

    path.write_text("\n".join(lines), encoding="utf-8")


def print_summary(selected: list[Candidate], rejected_similar: list[Candidate], args) -> None:
    print(f"Selected {len(selected)} prompts for {args.set_name}.")
    print(f"Rejected {len(rejected_similar)} near-duplicate candidates during selection.")
    domain_counts: dict[str, int] = {}
    for c in selected:
        domain_counts[c.domain] = domain_counts.get(c.domain, 0) + 1
    print("Domain coverage:")
    for domain in DOMAINS:
        print(f"  {domain}: {domain_counts.get(domain, 0)}")
    if selected:
        print("Top 5:")
        for c in selected[:5]:
            print(f"  {c.identifier}: {c.score:.2f}, {c.domain}, {len(c.wildcard_keys)} wildcards")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Curate a 1000-prompt style-generation publish set.")
    parser.add_argument("--db", default=DEFAULT_DB_PATH, help="Path to SQLite database.")
    parser.add_argument("--target", type=int, default=1000, help="Number of prompts to select.")
    parser.add_argument("--set-name", default="publish-curated-styles-1000", help="Prompt set name to create/update.")
    parser.add_argument("--duplicates-set", default="publish-curated-styles-duplicates-review", help="Optional review set for duplicate candidates. Empty disables it.")
    parser.add_argument("--candidate-set", default="publish-curated-styles-candidate-pool", help="Prompt set name for the larger retained candidate pool. Empty disables it.")
    parser.add_argument("--candidate-limit", type=int, default=70000, help="Maximum candidate-pool prompts to store in --candidate-set.")
    parser.add_argument("--duplicates-limit", type=int, default=1000, help="Maximum near-duplicate rejected prompts to place in the review set.")
    parser.add_argument("--pool-size", type=int, default=50000, help="Deprecated alias; use --pool-size-per-domain.")
    parser.add_argument("--pool-size-per-domain", type=int, default=10000, help="Top scored candidates retained per domain before diversity selection.")
    parser.add_argument("--max-scan", type=int, default=0, help="Maximum prompts to scan. 0 means full scan.")
    parser.add_argument("--min-wildcards", type=int, default=1, help="Require at least this many wildcards in the source template.")
    parser.add_argument("--similarity-threshold", type=float, default=0.72, help="Jaccard threshold for near-duplicate rejection.")
    parser.add_argument("--include-nsfw", action="store_true", help="Allow NSFW-ish prompt terms in the curated set.")
    parser.add_argument("--quality-wildcard-key", default="quality_modifier", help="Create/update this wildcard with generic quality terms when --write is used. Empty disables it.")
    parser.add_argument("--clean-quality-terms", action="store_true", help="Rewrite selected source templates so generic quality phrases become the quality wildcard.")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT, help="Markdown report path.")
    parser.add_argument("--write", action="store_true", help="Write prompt sets, metadata, and optional quality wildcard values to the database.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if "pool_size_per_domain" not in args or args.pool_size_per_domain is None:
        args.pool_size_per_domain = args.pool_size
    conn = get_connection(args.db)
    candidates = load_candidates(conn, args)
    selected, rejected_similar = choose_diverse(candidates, args.target, args.similarity_threshold)
    write_report(args.report, selected, rejected_similar, args)
    if args.write:
        write_database(conn, args, candidates, selected, rejected_similar)
    print_summary(selected, rejected_similar, args)
    print(f"Report written to {args.report}")
    if not args.write:
        print("Dry run only. Re-run with --write to update prompt_sets and prompt metadata.")


if __name__ == "__main__":
    main()
