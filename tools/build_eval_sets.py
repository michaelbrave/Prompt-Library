#!/usr/bin/env python3
"""Build stratified prompt evaluation sets from the local SQLite library."""

from __future__ import annotations

import argparse
import heapq
import json
import math
import random
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from prompt_library.db import DEFAULT_DB_PATH, get_connection
from prompt_library.wildcards import extract_wildcard_keys


DEFAULT_COMMON_TOKENS = ROOT / "inbox" / "rentry.org-1000 most common tokens.txt"
DEFAULT_REPORT_DIR = ROOT / "docs"

DOMAINS = [
    "photography",
    "anime-cartoon",
    "illustration-painting",
    "cgi-render",
    "mixed-hard-general",
]

SET_NAMES = {
    "photography": "eval-photography-25",
    "anime-cartoon": "eval-anime-cartoon-25",
    "illustration-painting": "eval-illustration-painting-25",
    "cgi-render": "eval-cgi-render-25",
}

DOMAIN_KEYWORDS = {
    "photography": {
        "photo",
        "photograph",
        "photographic",
        "photorealistic",
        "realistic",
        "raw photo",
        "dslr",
        "35mm",
        "85mm",
        "lens",
        "bokeh",
        "film grain",
        "studio",
        "portrait photography",
        "street photography",
        "cinematic still",
    },
    "anime-cartoon": {
        "anime",
        "manga",
        "cartoon",
        "comic",
        "chibi",
        "cel shading",
        "toon",
        "pixiv",
        "danbooru",
        "1girl",
        "1boy",
        "kawaii",
        "line art",
    },
    "illustration-painting": {
        "illustration",
        "painting",
        "oil painting",
        "watercolor",
        "gouache",
        "ink",
        "sketch",
        "concept art",
        "digital art",
        "artstation",
        "fine art",
        "brush",
        "canvas",
        "matte painting",
    },
    "cgi-render": {
        "3d",
        "cgi",
        "render",
        "octane",
        "unreal engine",
        "blender",
        "cinema 4d",
        "ray tracing",
        "rtx",
        "product render",
        "isometric",
        "low poly",
        "unity",
    },
}

TAG_KEYWORDS = {
    "portrait": {"portrait", "headshot", "face", "person", "woman", "man", "girl", "boy"},
    "character": {"character", "hero", "warrior", "mage", "person", "creature"},
    "landscape": {"landscape", "mountain", "forest", "desert", "ocean", "valley", "river"},
    "architecture": {"architecture", "building", "interior", "room", "city", "street", "house"},
    "product": {"product", "packaging", "shoe", "watch", "furniture", "vehicle", "car"},
    "lighting": {"lighting", "light", "shadow", "glow", "rim light", "golden hour", "volumetric"},
    "composition": {"composition", "close up", "wide angle", "full body", "top down", "macro"},
    "motion": {"motion", "running", "jumping", "flying", "dance", "action", "dynamic"},
}

DIFFICULTY_KEYWORDS = {
    "anatomy": {"hand", "hands", "finger", "fingers", "body", "pose", "face", "eyes"},
    "lighting": {"lighting", "reflection", "reflections", "rim light", "volumetric", "shadow"},
    "materials": {"glass", "metal", "fabric", "water", "skin", "hair", "fur", "leather"},
    "perspective": {"perspective", "wide angle", "fisheye", "top down", "isometric"},
    "multi-subject": {"crowd", "group", "two people", "multiple", "team"},
    "text-detail": {"sign", "logo", "typography", "lettering", "poster"},
}

VISUAL_TERMS = {
    "portrait",
    "landscape",
    "lighting",
    "composition",
    "camera",
    "lens",
    "environment",
    "background",
    "scene",
    "style",
    "color",
    "palette",
    "texture",
    "material",
    "pose",
    "action",
    "architecture",
    "product",
    "character",
    "illustration",
    "painting",
    "render",
    "photo",
}

PREFILTER_TERMS = {
    "photo",
    "portrait",
    "camera",
    "lighting",
    "cinematic",
    "anime",
    "cartoon",
    "illustration",
    "painting",
    "concept art",
    "watercolor",
    "render",
    "3d",
    "unreal",
    "blender",
    "product",
    "landscape",
    "architecture",
    "character",
    "environment",
    "composition",
    "style",
}

STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "into",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "with",
    "without",
}

GENERIC_PROMPT_TERMS = {
    "best quality",
    "masterpiece",
    "high quality",
    "highres",
    "8k",
    "4k",
    "detailed",
    "highly detailed",
    "ultra detailed",
    "beautiful",
    "amazing",
    "intricate",
}

NSFW_TERMS = {
    "nsfw",
    "nude",
    "naked",
    "nipples",
    "breasts",
    "cleavage",
    "pussy",
    "sex",
    "sexy",
    "seductive",
    "panties",
    "bra",
    "erotic",
    "explicit",
    "porn",
}

TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_-]*")
COMMON_TOKEN_RE = re.compile(r"^\s*\d+\s+(.+?)\s+\d+(?:\.\d+)?\s+\d+\s*$")


@dataclass(order=True)
class Candidate:
    sort_score: float
    prompt_id: int = field(compare=False)
    identifier: str = field(compare=False)
    concept: str = field(compare=False)
    template: str = field(compare=False)
    metadata: dict = field(compare=False)
    domain: str = field(compare=False)
    score: float = field(compare=False)
    tags: list[str] = field(compare=False)
    difficulty: list[str] = field(compare=False)
    wildcard_keys: list[str] = field(compare=False)
    seed: int = field(compare=False)
    reason: str = field(compare=False)
    signature: frozenset[str] = field(compare=False)


def tokenize(text: str) -> list[str]:
    return TOKEN_RE.findall(text.lower())


def phrase_hits(text: str, phrases: set[str]) -> int:
    lowered = text.lower()
    return sum(1 for phrase in phrases if phrase in lowered)


def load_common_tokens(path: Path) -> set[str]:
    if not path.exists():
        return set()

    tokens = set()
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            match = COMMON_TOKEN_RE.match(line)
            if match:
                phrase = match.group(1).strip().lower()
                tokens.add(phrase)
                tokens.update(tokenize(phrase))
    return tokens


def classify_domain(text: str) -> str:
    scores = {
        domain: phrase_hits(text, keywords)
        for domain, keywords in DOMAIN_KEYWORDS.items()
    }
    best_domain, best_score = max(scores.items(), key=lambda item: item[1])
    if best_score <= 0:
        return "mixed-hard-general"
    return best_domain


def classify_tags(text: str, groups: dict[str, set[str]]) -> list[str]:
    tags = [tag for tag, keywords in groups.items() if phrase_hits(text, keywords)]
    return tags[:6]


def length_score(word_count: int) -> float:
    if word_count < 6 or word_count > 120:
        return -8.0
    if 12 <= word_count <= 70:
        return 8.0
    if word_count < 12:
        return float(word_count - 4)
    return max(0.0, 8.0 - ((word_count - 70) / 8.0))


def signature_for(tokens: list[str], common_prompt_tokens: set[str]) -> frozenset[str]:
    ignored = STOPWORDS | GENERIC_PROMPT_TERMS | common_prompt_tokens
    useful = [token for token in tokens if len(token) > 2 and token not in ignored]
    return frozenset(useful[:80])


def jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def score_candidate(row, common_prompt_tokens: set[str], include_nsfw: bool) -> Candidate | None:
    template = row["positive_template"] or ""
    text = f"{row['concept']} {template}"
    lowered = text.lower()
    if not include_nsfw and any(term in lowered for term in NSFW_TERMS):
        return None

    tokens = tokenize(text)
    unique_tokens = set(tokens)
    if len(tokens) < 6:
        return None

    wildcard_keys = sorted(extract_wildcard_keys(template) - {"concept"})
    domain = classify_domain(text)
    tags = classify_tags(text, TAG_KEYWORDS)
    difficulty = classify_tags(text, DIFFICULTY_KEYWORDS)
    common_hits = len(unique_tokens & common_prompt_tokens)
    generic_hits = phrase_hits(text, GENERIC_PROMPT_TERMS)
    visual_hits = len(unique_tokens & VISUAL_TERMS) + sum(
        phrase_hits(text, keywords) for keywords in DOMAIN_KEYWORDS.values()
    )
    wildcard_score = min(len(wildcard_keys), 5) * 3.0
    tag_score = min(len(tags), 5) * 2.5
    difficulty_score = min(len(difficulty), 3) * 1.5
    specificity_score = math.log1p(len(unique_tokens - STOPWORDS)) * 3.0
    score = (
        length_score(len(tokens))
        + wildcard_score
        + tag_score
        + difficulty_score
        + visual_hits * 1.25
        + specificity_score
        - generic_hits * 1.4
        - common_hits * 0.45
    )

    if domain == "mixed-hard-general":
        score += min(len(difficulty), 4) * 1.8

    if score < 8.0:
        return None

    seed_basis = f"{row['identifier']}|{row['id']}"
    seed = random.Random(seed_basis).randint(1, 2_147_483_647)
    reason_parts = [
        f"{domain} coverage",
        f"{len(wildcard_keys)} wildcard categories",
        f"{len(tags)} visual tags",
    ]
    if difficulty:
        reason_parts.append("difficulty: " + ", ".join(difficulty[:3]))

    metadata = json.loads(row["metadata"] or "{}")
    return Candidate(
        sort_score=score,
        prompt_id=row["id"],
        identifier=row["identifier"],
        concept=row["concept"],
        template=template,
        metadata=metadata,
        domain=domain,
        score=score,
        tags=tags,
        difficulty=difficulty,
        wildcard_keys=wildcard_keys,
        seed=seed,
        reason="; ".join(reason_parts),
        signature=signature_for(tokens, common_prompt_tokens),
    )


def load_candidate_pool(
    conn,
    common_prompt_tokens: set[str],
    include_nsfw: bool,
    heap_size: int,
    prefilter: bool,
    bound_only: bool,
    max_scan: int | None,
) -> dict[str, list[Candidate]]:
    cursor = conn.cursor()
    params: list[str] = []
    prefilter_sql = ""
    if prefilter:
        clauses = ["pt.positive_template LIKE '%{%'"]
        for term in sorted(PREFILTER_TERMS):
            clauses.append("LOWER(pt.positive_template) LIKE ?")
            clauses.append("LOWER(p.concept) LIKE ?")
            pattern = f"%{term}%"
            params.extend([pattern, pattern])
        prefilter_sql = "AND (" + " OR ".join(clauses) + ")"

    if bound_only:
        sql = f"""
            SELECT p.id, p.identifier, p.concept, p.metadata, pt.positive_template
            FROM prompt_wildcard_bindings pwb
            JOIN prompts p ON p.id = pwb.prompt_id
            JOIN prompt_templates pt ON pt.prompt_id = p.id
            WHERE p.status = 'active' AND pt.enabled = 1
            {prefilter_sql}
        """
    else:
        sql = f"""
            SELECT p.id, p.identifier, p.concept, p.metadata, pt.positive_template
            FROM prompts p
            JOIN prompt_templates pt ON pt.prompt_id = p.id
            WHERE p.status = 'active' AND pt.enabled = 1
            {prefilter_sql}
        """

    cursor.execute(sql, params)

    heaps: dict[str, list[Candidate]] = {domain: [] for domain in DOMAINS}
    seen_prompt_ids: set[int] = set()
    for row in cursor:
        prompt_id = row["id"]
        if prompt_id in seen_prompt_ids:
            continue
        seen_prompt_ids.add(prompt_id)
        if max_scan is not None and len(seen_prompt_ids) > max_scan:
            break
        candidate = score_candidate(row, common_prompt_tokens, include_nsfw)
        if candidate is None:
            continue
        heap = heaps[candidate.domain]
        if len(heap) < heap_size:
            heapq.heappush(heap, candidate)
        elif candidate.score > heap[0].score:
            heapq.heapreplace(heap, candidate)

    return {
        domain: sorted(heap, key=lambda item: item.score, reverse=True)
        for domain, heap in heaps.items()
    }


def choose_diverse(
    pool: list[Candidate],
    target: int,
    used_ids: set[int] | None = None,
    similarity_threshold: float = 0.72,
) -> list[Candidate]:
    selected: list[Candidate] = []
    used_ids = used_ids or set()
    tag_counts: dict[str, int] = {}

    for candidate in pool:
        if candidate.prompt_id in used_ids:
            continue
        if any(jaccard(candidate.signature, item.signature) >= similarity_threshold for item in selected):
            continue
        if candidate.tags and max(tag_counts.get(tag, 0) for tag in candidate.tags) >= max(3, target // 4):
            continue

        selected.append(candidate)
        used_ids.add(candidate.prompt_id)
        for tag in candidate.tags:
            tag_counts[tag] = tag_counts.get(tag, 0) + 1
        if len(selected) >= target:
            break

    if len(selected) < target:
        for candidate in pool:
            if candidate.prompt_id in used_ids:
                continue
            if any(jaccard(candidate.signature, item.signature) >= 0.86 for item in selected):
                continue
            selected.append(candidate)
            used_ids.add(candidate.prompt_id)
            if len(selected) >= target:
                break

    return selected


def domain_quotas(target: int) -> dict[str, int]:
    base = target // len(DOMAINS)
    remainder = target % len(DOMAINS)
    return {
        domain: base + (1 if index < remainder else 0)
        for index, domain in enumerate(DOMAINS)
    }


def build_sets(pools: dict[str, list[Candidate]], target: int, specialized_target: int) -> dict[str, list[Candidate]]:
    sets: dict[str, list[Candidate]] = {}
    core: list[Candidate] = []
    used_ids: set[int] = set()

    for domain, quota in domain_quotas(target).items():
        selected = choose_diverse(pools[domain], quota, used_ids)
        core.extend(selected)

    if len(core) < target:
        combined = sorted(
            [candidate for pool in pools.values() for candidate in pool],
            key=lambda item: item.score,
            reverse=True,
        )
        core.extend(choose_diverse(combined, target - len(core), used_ids))

    sets[f"eval-core-{target}"] = core[:target]

    for domain, set_name in SET_NAMES.items():
        sets[set_name] = choose_diverse(pools[domain], specialized_target)

    return sets


def update_prompt_metadata(cursor, candidate: Candidate) -> None:
    metadata = dict(candidate.metadata)
    metadata["eval_selection"] = {
        "eval_domain": candidate.domain,
        "eval_tags": candidate.tags,
        "selection_reason": candidate.reason,
        "difficulty": candidate.difficulty,
        "default_render_seed": candidate.seed,
        "score": round(candidate.score, 2),
        "wildcard_keys": candidate.wildcard_keys,
    }
    cursor.execute(
        "UPDATE prompts SET metadata = ?, updated_at = datetime('now') WHERE id = ?",
        (json.dumps(metadata, sort_keys=True), candidate.prompt_id),
    )


def write_sets(conn, sets: dict[str, list[Candidate]], dry_run: bool) -> None:
    if dry_run:
        return

    cursor = conn.cursor()
    for set_name, candidates in sets.items():
        if set_name.startswith("eval-core-"):
            description = "Stratified core prompt benchmark for model-to-model evaluation."
            tags = ["evaluation", "core", "benchmark"]
        else:
            domain = next(key for key, value in SET_NAMES.items() if value == set_name)
            description = f"Domain-focused evaluation prompts for {domain}."
            tags = ["evaluation", domain]

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
            (
                set_name,
                description,
                json.dumps(tags),
                json.dumps({"builder": "tools/build_eval_sets.py", "member_count": len(candidates)}),
            ),
        )
        cursor.execute("SELECT id FROM prompt_sets WHERE name = ?", (set_name,))
        prompt_set_id = cursor.fetchone()["id"]
        cursor.execute("DELETE FROM prompt_set_members WHERE prompt_set_id = ?", (prompt_set_id,))

        for position, candidate in enumerate(candidates, start=1):
            cursor.execute(
                """
                INSERT INTO prompt_set_members (prompt_set_id, prompt_id, position, enabled)
                VALUES (?, ?, ?, 1)
                """,
                (prompt_set_id, candidate.prompt_id, position),
            )
            update_prompt_metadata(cursor, candidate)

    conn.commit()


def write_report(report_path: Path, sets: dict[str, list[Candidate]], dry_run: bool) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Evaluation Prompt Sets",
        "",
        "Generated by `tools/build_eval_sets.py`.",
        "",
        "Selection uses prompt specificity, useful wildcard coverage, visual-domain keywords, difficulty tags, and approximate similarity pruning. Common prompt tokens are used as a penalty so generic boilerplate does not dominate the selections.",
        "",
        "These sets are intended as a first-pass evaluation layer. After the pool is narrowed and reviewed, selected prompts should still be transcribed into the repository's different prompt-style variants.",
        "",
    ]
    if dry_run:
        lines.extend(["Dry run only; the database was not changed.", ""])

    for set_name, candidates in sets.items():
        lines.extend([f"## {set_name}", ""])
        lines.extend([
            "| # | Identifier | Domain | Score | Tags | Wildcards | Reason |",
            "|---:|---|---|---:|---|---|---|",
        ])
        for index, candidate in enumerate(candidates, start=1):
            tags = ", ".join(candidate.tags) or "-"
            wildcards = ", ".join(candidate.wildcard_keys) or "-"
            reason = candidate.reason.replace("|", "/")
            lines.append(
                f"| {index} | `{candidate.identifier}` | {candidate.domain} | {candidate.score:.2f} | {tags} | {wildcards} | {reason} |"
            )
        lines.append("")

    report_path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build stratified prompt evaluation sets.")
    parser.add_argument("--db", default=DEFAULT_DB_PATH, help="Path to SQLite database.")
    parser.add_argument("--target", type=int, default=100, help="Core eval set size.")
    parser.add_argument("--specialized-target", type=int, default=25, help="Domain eval set size.")
    parser.add_argument("--common-tokens", type=Path, default=DEFAULT_COMMON_TOKENS, help="Common token list used for boilerplate penalties.")
    parser.add_argument("--report", type=Path, default=None, help="Markdown report path.")
    parser.add_argument("--heap-size", type=int, default=2500, help="Candidate pool size retained per domain.")
    parser.add_argument("--prefilter", action="store_true", help="Apply a SQL visual-keyword prefilter before Python scoring.")
    parser.add_argument("--include-unbound", action="store_true", help="Also scan prompts that have no wildcard bindings.")
    parser.add_argument("--max-scan", type=int, default=50000, help="Maximum distinct prompts to score; use 0 for a full scan.")
    parser.add_argument("--include-nsfw", action="store_true", help="Allow explicit/adult prompts in eval sets.")
    parser.add_argument("--dry-run", action="store_true", help="Build and report selections without writing SQLite changes.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.target <= 0 or args.specialized_target <= 0:
        raise SystemExit("--target and --specialized-target must be positive")

    report_path = args.report or DEFAULT_REPORT_DIR / f"eval-core-{args.target}.md"
    common_prompt_tokens = load_common_tokens(args.common_tokens)
    common_prompt_tokens.update(GENERIC_PROMPT_TERMS)

    conn = get_connection(args.db)
    pools = load_candidate_pool(
        conn,
        common_prompt_tokens,
        args.include_nsfw,
        args.heap_size,
        args.prefilter,
        not args.include_unbound,
        None if args.max_scan == 0 else args.max_scan,
    )
    sets = build_sets(pools, args.target, args.specialized_target)

    missing = {name: size for name, size in ((name, len(items)) for name, items in sets.items()) if size == 0}
    if missing:
        raise SystemExit(f"No candidates selected for: {', '.join(missing)}")

    write_sets(conn, sets, args.dry_run)
    write_report(report_path, sets, args.dry_run)

    for set_name, candidates in sets.items():
        print(f"{set_name}: {len(candidates)} prompts")
    print(f"Report written to {report_path}")
    if args.dry_run:
        print("Dry run: database not changed")


if __name__ == "__main__":
    main()
