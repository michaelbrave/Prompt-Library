#!/usr/bin/env python3
"""Prepare prompt text files from inbox/ for database import.

The inbox contains raw OCR/book exports, so this script is intentionally more
conservative than clean_prompts.py. It extracts likely image-generation prompt
lines, rejects obvious prose/table-of-contents material, and writes chunked JSON
seed files that can be imported with prompt-library.
"""

import argparse
import datetime
import html
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from clean_prompts import (
    clean_positive_prompt,
    extract_negative_prompt,
    generate_concept,
    generate_style_variations,
    should_reject_prompt,
)


DEFAULT_INBOX = Path("inbox")
DEFAULT_OUTPUT = Path("seeds/inbox")
DEFAULT_CHUNK_SIZE = 500

IMAGE_TERMS = re.compile(
    r"\b("
    r"image|photo|photograph|portrait|painting|illustration|render|art|artwork|"
    r"scene|landscape|cityscape|character|anime|cinematic|macro|studio|"
    r"midjourney|stable diffusion|dall-?e|prompt|/imagine|--ar|--v|--style"
    r")\b",
    re.IGNORECASE,
)
ENTRY_START = re.compile(
    r"^\s*(?:"
    r"(?:prompt\s*)?\d{1,5}\s*[\.):-]\s*|"
    r"prompt\s*\d{0,5}\s*[:.-]\s*|"
    r"/imagine\s+prompt:?\s*"
    r")",
    re.IGNORECASE,
)
ENTRY_PREFIX = re.compile(
    r"^\s*(?:prompt\s*)?\d{1,5}\s*[\.):-]\s*|"
    r"^\s*prompt\s*\d{0,5}\s*[:.-]\s*|"
    r"^\s*/imagine\s+prompt:?\s*",
    re.IGNORECASE,
)
BAD_LINE = re.compile(
    r"\b("
    r"copyright|all rights reserved|table of contents|contents|introduction|"
    r"chapter|page|click|download|subscribe|website|email|isbn|"
    r"how to use|description:|prompt style|negative prompt$|"
    r"this book|this collection|guidebook|novice|experienced practitioner|"
    r"prompt engineering|effective prompts|iterate and refine|review the results|"
    r"be aware that|deep[- ]dive|read our|google sheets|"
    r"cross[- ]promotion|social media|customer|customers|sales|business|"
    r"asset store|your assets|your products|promote your|"
    r"available prompts|desired image|desired imagery|structure of a prompt|"
    r"rendering keywords|consider context|refer to the|to achieve desirable|"
    r"iterative refinement|generated images|generate images using|"
    r"first of all|thanks a lot|your purchase|in this volume|you.ll learn|"
    r"market is thriving|in high demand|assist you in|allow you to upload|"
    r"midjourney documentation|technology works|make money"
    r")\b",
    re.IGNORECASE,
)
LIST_HEADING = re.compile(r"^\s*(artists|genres|techniques|photographers|aesthetics)\b", re.IGNORECASE)
PROMPT_START = re.compile(
    r"^\s*(a|an|the|create|generate|imagine|depict|visualize|craft|design|draw|"
    r"paint|render|capture|illustrate|make|produce|compose|show|portrait|photo|"
    r"cinematic|macro|studio|editorial|anime|abstract|surreal|futuristic)\b",
    re.IGNORECASE,
)
PAGE_NUMBER = re.compile(r"^\s*\d{1,4}\s*$")
SPACES = re.compile(r"\s+")


def slugify(value, max_length=72):
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return (value or "source")[:max_length].strip("_")


def read_text(path):
    return path.read_text(encoding="utf-8", errors="ignore").replace("\x00", "")


def normalize_line(line):
    line = html.unescape(line)
    line = line.replace("ﬁ", "fi").replace("ﬂ", "fl")
    line = line.replace("—", "-").replace("–", "-")
    return SPACES.sub(" ", line).strip()


def iter_prompt_blocks(text):
    lines = [normalize_line(line) for line in text.splitlines()]
    current = []

    def flush():
        nonlocal current
        if current:
            block = " ".join(current).strip()
            current = []
            if block:
                return block
        return None

    for line in lines:
        if not line:
            block = flush()
            if block:
                yield block
            continue
        if PAGE_NUMBER.match(line):
            continue
        if ENTRY_START.match(line):
            block = flush()
            if block:
                yield block
            current = [ENTRY_PREFIX.sub("", line).strip()]
            continue
        if current:
            current.append(line)
            continue
        yield line

    block = flush()
    if block:
        yield block


def looks_like_prompt(text):
    text = normalize_line(text)
    if len(text) < 30 or len(text) > 900:
        return False
    if BAD_LINE.search(text):
        return False
    if re.match(r"^\s*\d+(?:\.\d+)+\s+\w+", text):
        return False
    if LIST_HEADING.match(text):
        return False
    if text.count(".") >= 5 and "," not in text and "--" not in text:
        return False
    if not any(char.isalpha() for char in text):
        return False
    has_visual_term = bool(IMAGE_TERMS.search(text))
    has_prompt_shape = "," in text or "--" in text or "/imagine" in text.lower()
    starts_like_prompt = bool(PROMPT_START.match(text))
    return has_visual_term and (has_prompt_shape or starts_like_prompt)


def prompt_entry(source_slug, source_name, source_file, index, raw):
    positive_raw, negative_raw = extract_negative_prompt(raw)
    metadata = {
        "original_source": source_name,
        "original_prompt": raw,
        "date_added": datetime.datetime.now().isoformat(),
        "source_file": source_file,
        "source_index": index,
        "ingestion_path": "tools/prepare_inbox.py",
    }
    positive = clean_positive_prompt(positive_raw, metadata)
    if negative_raw:
        metadata["original_negative_prompt"] = negative_raw
    reject, reason = should_reject_prompt(positive, metadata)
    if reject:
        return None, {
            "index": index,
            "reason": reason,
            "original": raw[:240],
            "metadata": metadata,
        }

    concept = generate_concept(positive)
    return {
        "identifier": f"{source_slug}_{index:05d}",
        "concept": concept,
        "status": "active",
        "metadata": metadata,
        "wildcard_refs": [],
        "style_variations": generate_style_variations(positive, raw),
    }, None


def chunks(items, size):
    for index in range(0, len(items), size):
        yield index // size + 1, items[index:index + size]


def prepare_file(path, output_dir, chunk_size, dry_run=False):
    source_slug = slugify(path.stem)
    source_name = f"inbox_{source_slug}"
    prompts = []
    rejected = []
    seen = set()

    for index, block in enumerate(iter_prompt_blocks(read_text(path))):
        if not looks_like_prompt(block):
            continue
        key = normalize_line(block).lower()
        if key in seen:
            continue
        seen.add(key)
        entry, rejection = prompt_entry(source_slug, source_name, path.name, len(prompts), block)
        if entry:
            prompts.append(entry)
        elif rejection:
            rejected.append(rejection)

    outputs = []
    if not dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)
        for stale in output_dir.glob(f"{source_slug}_part*_cleaned.json"):
            stale.unlink()
        stale_rejected = output_dir / f"{source_slug}_rejected.json"
        if stale_rejected.exists():
            stale_rejected.unlink()
        for part, prompt_chunk in chunks(prompts, chunk_size):
            output_path = output_dir / f"{source_slug}_part{part:03d}_cleaned.json"
            output_path.write_text(
                json.dumps({"wildcard_library": {}, "prompt_identifiers": prompt_chunk}, indent=2),
                encoding="utf-8",
            )
            outputs.append(output_path)
        rejected_path = output_dir / f"{source_slug}_rejected.json"
        rejected_path.write_text(json.dumps(rejected, indent=2), encoding="utf-8")

    return {
        "source": str(path),
        "slug": source_slug,
        "prompts": len(prompts),
        "rejected": len(rejected),
        "chunks": len(outputs) if outputs else (len(prompts) + chunk_size - 1) // chunk_size,
        "outputs": [str(path) for path in outputs],
    }


def discover_sources(inbox_dir):
    return sorted(
        path for path in inbox_dir.glob("*.txt")
        if path.is_file() and path.stat().st_size > 0
    )


def main():
    parser = argparse.ArgumentParser(description="Extract and chunk inbox prompt text files into JSON seeds.")
    parser.add_argument("--inbox", type=Path, default=DEFAULT_INBOX, help="Inbox directory")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output seed directory")
    parser.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE, help="Prompts per cleaned seed file")
    parser.add_argument("--dry-run", action="store_true", help="Report counts without writing seed files")
    parser.add_argument("files", nargs="*", type=Path, help="Specific text files to prepare")
    args = parser.parse_args()

    sources = args.files or discover_sources(args.inbox)
    manifest = []
    for source in sources:
        result = prepare_file(source, args.output, args.chunk_size, dry_run=args.dry_run)
        manifest.append(result)
        print(f"{source}: {result['prompts']} prompts, {result['rejected']} rejected, {result['chunks']} chunks")

    if not args.dry_run:
        args.output.mkdir(parents=True, exist_ok=True)
        manifest_path = args.output / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print(f"Wrote manifest: {manifest_path}")


if __name__ == "__main__":
    main()
