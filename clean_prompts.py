#!/usr/bin/env python3
"""Universal prompt cleaner - handles multiple input formats with auto-detection.

Usage:
    python3 clean_prompts.py input.txt --source mysource
    python3 clean_prompts.py input.txt --source mysource --format raw
    python3 clean_prompts.py input.txt --source mysource --dry-run

Auto-detects format from content:
    dream_factory  - Dream Factory .prompts format ([config], [prompts], !SETTING=)
    structured     - Structured fields (Subject:, Clothing:, Environment:, etc.)
    sectioned      - Section headers (### Midjourney Prompts)
    raw            - Plain text, one prompt per blank-line-separated block
"""

import re
import json
import datetime
import argparse
import sys
from collections import defaultdict
from pathlib import Path


# ── Regex patterns ──────────────────────────────────────────────────────────

MJ_PARAM_PATTERN = re.compile(
    r'--(?:ar|chaos|stylize|style|stylea|v|q|niji|raw|quality|personalize|profile|s|c)(?:\s+[\S]+)?',
    re.IGNORECASE
)
LORA_SYNTAX = re.compile(r'\s*<lora:[^>]+>')
WEIGHTED_PARENS = re.compile(r'\(([^:)]+):\d+\.\d+\)')
BRACKET_WEIGHT = re.compile(r'\[([^:\]]+):\d+\.\d+\]')
ALT_SYNTAX = re.compile(r'\[([^\]|]+)\|[^\]]+\]')
ATTENTION_SYNTAX = re.compile(r'::\d+')
DOUBLE_BRACE = re.compile(r'\{\{\s*([^}]+)\s*\}\}')
NEGATIVE_PREFIX = re.compile(r'^(?:Negative prompt|negative prompts)\s*:', re.IGNORECASE)
TRAILING_DASH = re.compile(r'\s+-\s*$')
MULTI_PARENS = re.compile(r'\({2,}([^)]+)\){2,}')
JSON_BLOCK = re.compile(r'^\s*\{.*\}\s*$', re.DOTALL)

# CivitAI/Danbooru-specific tokens
SCORE_TAG = re.compile(r'\bscore_\d+\b')
ARTIST_TAG = re.compile(r'@\w+(?:[\s_]\w+)*')
BREAK_KEYWORD = re.compile(r'\bBREAK\b')
MODEL_MARKER = re.compile(r'^(?:ye-pop|ye_pop)\s*', re.MULTILINE)

# Dream Factory patterns
DF_CONFIG_PATTERN = re.compile(r'\[config\]', re.IGNORECASE)
DF_PROMPTS_PATTERN = re.compile(r'\[prompts\]', re.IGNORECASE)
DF_SETTING_PATTERN = re.compile(r'^!(\w+)\s*=\s*(.+)$', re.MULTILINE)
DF_NEG_PROMPT_PATTERN = re.compile(r'^!NEG_PROMPT\s*=\s*(.+)$', re.MULTILINE)

# Structured fields patterns
KNOWN_FIELDS = [
    "Subject", "Clothing", "Action", "Environment", "Camera",
    "Lighting", "Objects", "Style Details", "Hair", "Accessories"
]
FIELD_PATTERN = re.compile(
    r'^(' + '|'.join(KNOWN_FIELDS) + r')\s*:\s*(.+)$',
    re.IGNORECASE
)

# Section header pattern (PromptHero style)
SECTION_HEADER = re.compile(r'^###\s+(.+?)\s*$', re.MULTILINE)

# LoRA style replacement map
LORA_STYLE_MAP = {
    "niji3d": "anime 3D render style, cel-shaded anime aesthetic",
    "edg90hh": "urban streetwear style, edgy fashion",
}


# ── Format detection ────────────────────────────────────────────────────────

def detect_format(text):
    """Auto-detect input format from content."""
    # Dream Factory: has [config] or [prompts] sections
    if DF_CONFIG_PATTERN.search(text) or DF_PROMPTS_PATTERN.search(text):
        return "dream_factory"

    # Structured fields: majority of non-empty lines match Field: Value
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    if lines:
        field_lines = sum(1 for l in lines if FIELD_PATTERN.match(l))
        if field_lines / len(lines) > 0.5:
            return "structured"

    # Sectioned: has ### headers
    if SECTION_HEADER.search(text):
        return "sectioned"

    return "raw"


# ── Parsers ─────────────────────────────────────────────────────────────────

def parse_dream_factory(text):
    """Parse Dream Factory .prompts format."""
    header_lines = []
    config_block = ""
    prompts_blocks = []
    current_section = "header"
    current_prompts = []

    for line in text.split('\n'):
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            if current_section == "header":
                header_lines.append(stripped)
            continue
        if DF_CONFIG_PATTERN.match(stripped):
            current_section = "config"
            continue
        if DF_PROMPTS_PATTERN.match(stripped):
            if current_prompts:
                prompts_blocks.append(current_prompts)
            current_prompts = []
            current_section = "prompts"
            continue
        if current_section == "config":
            config_block += line + '\n'
        elif current_section == "prompts":
            current_prompts.append(stripped)

    if current_prompts:
        prompts_blocks.append(current_prompts)

    settings = {}
    for match in DF_SETTING_PATTERN.finditer(config_block):
        settings[match.group(1)] = match.group(2).strip()

    neg_prompt = ""
    neg_match = DF_NEG_PROMPT_PATTERN.search(config_block)
    if neg_match:
        neg_prompt = neg_match.group(1).strip()

    info = {}
    for line in header_lines:
        if line.startswith('#') and ':' in line:
            parts = line.lstrip('# ').split(':', 1)
            if len(parts) == 2:
                info[parts[0].strip().lower().replace(' ', '_')] = parts[1].strip()

    return {
        "header_info": info,
        "settings": settings,
        "negative_prompt": neg_prompt,
        "prompts_blocks": prompts_blocks,
    }


def parse_sectioned(text):
    """Parse sectioned format (### headers with prompts below)."""
    # Normalize: ensure text starts with newline so regex matches first header
    if not text.startswith('\n'):
        text = '\n' + text

    sections = re.split(r'\n###\s+(.+?)\s*\n', text)
    result = []
    current_section = "stable-diffusion"

    i = 0
    while i < len(sections):
        part = sections[i].strip()
        if not part:
            i += 1
            continue
        # Check if this part is a section header name
        if any(part.startswith(s) for s in ["Midjourney", "Nano", "Flux"]):
            current_section = part.strip().lower().replace(" prompts", "").replace(" prommpts", "").replace(" ", "-")
            i += 1
            continue
        # This is prompt content
        prompts = re.split(r'\n\s*\n', part)
        for p in prompts:
            p = p.strip()
            if p:
                result.append({"raw": p, "section": current_section})
        i += 1
    return result


def parse_structured(text):
    """Parse structured fields format into individual prompt blocks."""
    lines = text.split('\n')
    prompts = []
    current = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        is_field = bool(FIELD_PATTERN.match(stripped))
        if not is_field and current:
            last_was_field = any(FIELD_PATTERN.match(l.strip()) for l in current if l.strip())
            if last_was_field:
                prompts.append('\n'.join(current))
                current = [stripped]
            else:
                current.append(stripped)
        elif not is_field and not current:
            current.append(stripped)
        else:
            current.append(stripped)

    if current:
        prompts.append('\n'.join(current))

    return [{"raw": p, "section": "structured"} for p in prompts]


def parse_raw(text):
    """Parse raw text - one prompt per blank-line-separated block."""
    blocks = re.split(r'\n\s*\n', text)
    result = []
    for block in blocks:
        block = block.strip()
        if block:
            result.append({"raw": block, "section": "raw"})
    return result


# ── Cleaning pipeline ───────────────────────────────────────────────────────

def extract_negative_prompt(prompt_text):
    """Extract negative prompt from text if present."""
    lines = prompt_text.split("\n")
    positive_lines = []
    negative_text = None
    for line in lines:
        if NEGATIVE_PREFIX.match(line.strip()):
            negative_text = NEGATIVE_PREFIX.sub("", line.strip()).strip()
        else:
            positive_lines.append(line)
    return "\n".join(positive_lines).strip(), negative_text


def clean_positive_prompt(text, metadata):
    """Apply all cleaning transformations to a positive prompt."""
    original = text

    # LoRA handling
    lora_matches = LORA_SYNTAX.findall(text)
    if lora_matches:
        for lora in lora_matches:
            lora_name = lora.split(":")[1].split(">")[0].split(":")[0]
            if lora_name in LORA_STYLE_MAP:
                replacement = LORA_STYLE_MAP[lora_name]
                text = text.replace(lora, f", {replacement}")
                metadata["lora_replaced"] = metadata.get("lora_replaced", []) + [
                    {"name": lora_name, "replaced_with": replacement}
                ]
            else:
                text = LORA_SYNTAX.sub("", text, count=1)
                metadata["lora_removed"] = metadata.get("lora_removed", []) + [{"name": lora_name}]

    # MJ params
    if MJ_PARAM_PATTERN.search(original):
        metadata["mj_params_removed"] = True
    text = MJ_PARAM_PATTERN.sub("", text)

    # Strip weight syntax
    def replace_weighted(m):
        return m.group(1)
    text = WEIGHTED_PARENS.sub(replace_weighted, text)
    text = BRACKET_WEIGHT.sub(replace_weighted, text)

    # Strip alt syntax
    def replace_alt(m):
        return m.group(1)
    text = ALT_SYNTAX.sub(replace_alt, text)

    # Strip attention syntax
    text = ATTENTION_SYNTAX.sub("", text)

    # Strip double braces
    def replace_brace(m):
        return m.group(1)
    text = DOUBLE_BRACE.sub(replace_brace, text)

    # Strip multi-parens
    text = MULTI_PARENS.sub(r'\1', text)

    # CivitAI/Danbooru-specific tokens (after syntax stripping so @[...] patterns are resolved)
    text = SCORE_TAG.sub("", text)
    text = ARTIST_TAG.sub("", text)
    text = BREAK_KEYWORD.sub("", text)
    text = MODEL_MARKER.sub("", text)
    if SCORE_TAG.search(original) or ARTIST_TAG.search(original) or BREAK_KEYWORD.search(original) or MODEL_MARKER.search(original):
        metadata["civitai_tokens_stripped"] = True

    # Cleanup
    text = TRAILING_DASH.sub("", text)
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'\s*,\s*', ', ', text)
    text = re.sub(r',\s*,', ',', text)
    text = text.strip().strip(",.")

    return text


def detect_json_structure(text):
    """Check if text is a JSON block."""
    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, dict):
                return True, parsed
        except json.JSONDecodeError:
            pass
    return False, None


def has_prose_structure(text):
    """Check if text reads like prose (multiple full sentences)."""
    sentences = re.split(r'[.!?]+', text)
    full_sentences = [s.strip() for s in sentences if len(s.strip()) > 30]
    return len(full_sentences) >= 2


def has_weighted_syntax(original_text):
    """Check if original text had weighted syntax."""
    return bool(re.search(r'\([^)]+:\d+\.\d+\)', original_text)) or \
           bool(re.search(r'\[[^:\]]+:\d+\.\d+\]', original_text))


# ── Style variant generators ───────────────────────────────────────────────

def parse_structured_fields(text):
    """Parse structured fields from text."""
    fields = {}
    concept_lines = []
    for line in text.split('\n'):
        stripped = line.strip()
        if not stripped:
            continue
        match = FIELD_PATTERN.match(stripped)
        if match:
            field_name = match.group(1)
            field_value = match.group(2).strip()
            normalized = field_name.strip()
            if normalized in fields:
                fields[normalized] += " " + field_value
            else:
                fields[normalized] = field_value
        else:
            concept_lines.append(stripped)
    concept = " ".join(concept_lines).strip()
    if not concept and fields:
        subject = fields.get("Subject", "")
        env = fields.get("Environment", "")
        concept = f"{subject}, {env}".strip(", ")
    return concept, fields


def fields_to_comma_separated(fields):
    parts = []
    for field_name in KNOWN_FIELDS:
        if field_name in fields:
            parts.append(fields[field_name])
    return ", ".join(parts)


def fields_to_everyday_speech(fields, concept):
    parts = []
    if "Subject" in fields:
        parts.append(fields["Subject"])
    if "Clothing" in fields:
        parts.append(f"wearing {fields['Clothing']}")
    if "Action" in fields:
        parts.append(fields["Action"])
    if "Environment" in fields:
        parts.append(f"in {fields['Environment']}")
    base = " ".join(parts) if parts else concept
    modifiers = []
    if "Camera" in fields:
        modifiers.append(fields["Camera"])
    if "Lighting" in fields:
        modifiers.append(f"with {fields['Lighting']}")
    if "Style Details" in fields:
        modifiers.append(fields["Style Details"])
    if modifiers:
        base += ". " + ". ".join(modifiers)
    return base


def fields_to_enhanced(fields, concept):
    parts = []
    if "Style Details" in fields:
        parts.append(f"({fields['Style Details']}:1.2)")
    if "Subject" in fields:
        parts.append(f"({fields['Subject']}:1.1)")
    for field_name in ["Clothing", "Action", "Environment", "Camera", "Lighting", "Objects", "Hair", "Accessories"]:
        if field_name in fields:
            parts.append(fields[field_name])
    return ", ".join(parts)


def generate_style_variations(positive_cleaned, original_raw, is_json=False, structured_fields=None):
    """Generate style variants from cleaned prompt text."""
    style_variations = []

    if is_json:
        style_variations.append({
            "identifier": "lisp-like",
            "syntax_family": "lisp-like",
            "positive_template": positive_cleaned,
            "negative_template": "",
            "negative_prompt_strategy": "structured"
        })
        return style_variations

    if structured_fields:
        # Structured fields: generate all 4 variants
        style_variations.append({
            "identifier": "structured-fields",
            "syntax_family": "structured-fields",
            "positive_template": original_raw.strip(),
            "negative_template": "",
            "negative_prompt_strategy": "structured"
        })
        style_variations.append({
            "identifier": "comma-separated",
            "syntax_family": "comma-separated",
            "positive_template": fields_to_comma_separated(structured_fields),
            "negative_template": "",
            "negative_prompt_strategy": "standard"
        })
        style_variations.append({
            "identifier": "everyday-speech",
            "syntax_family": "everyday-speech",
            "positive_template": fields_to_everyday_speech(structured_fields, ""),
            "negative_template": "",
            "negative_prompt_strategy": "minimal"
        })
        style_variations.append({
            "identifier": "enhanced-prompt",
            "syntax_family": "enhanced-prompt",
            "positive_template": fields_to_enhanced(structured_fields, ""),
            "negative_template": "",
            "negative_prompt_strategy": "weighted"
        })
        return style_variations

    # Raw/sectioned text: always comma-separated
    style_variations.append({
        "identifier": "comma-separated",
        "syntax_family": "comma-separated",
        "positive_template": positive_cleaned,
        "negative_template": "",
        "negative_prompt_strategy": "standard"
    })

    # everyday-speech if prose-like
    if has_prose_structure(positive_cleaned):
        style_variations.append({
            "identifier": "everyday-speech",
            "syntax_family": "everyday-speech",
            "positive_template": positive_cleaned,
            "negative_template": "",
            "negative_prompt_strategy": "minimal"
        })

    # enhanced-prompt if original had weights
    if has_weighted_syntax(original_raw):
        style_variations.append({
            "identifier": "enhanced-prompt",
            "syntax_family": "enhanced-prompt",
            "positive_template": positive_cleaned,
            "negative_template": "",
            "negative_prompt_strategy": "weighted"
        })

    # structured-fields variant (same text, different interpretation)
    style_variations.append({
        "identifier": "structured-fields",
        "syntax_family": "structured-fields",
        "positive_template": positive_cleaned,
        "negative_template": "",
        "negative_prompt_strategy": "standard"
    })

    return style_variations


# ── Helpers ─────────────────────────────────────────────────────────────────

def generate_identifier(concept, index):
    words = concept.lower().split()[:4]
    slug = "_".join(re.sub(r'[^a-z0-9]', '', w) for w in words if w)
    if not slug:
        slug = "prompt"
    return f"{slug}_{index:03d}"


def generate_concept(text, max_words=8):
    text = re.sub(r'[^a-zA-Z\s]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    words = text.split()[:max_words]
    return " ".join(words) if words else text[:50]


def should_reject_prompt(positive, metadata):
    if not positive or len(positive.strip()) < 15:
        return True, f"too short after cleaning ({len(positive.strip())} chars)"
    word_count = len(positive.split())
    if word_count < 3:
        return True, f"too few words after cleaning ({word_count} words)"
    if not any(c.isalpha() for c in positive):
        return True, "no alphabetic content after cleaning"
    # LoRA removal alone is not grounds for rejection if content remains valid
    return False, None


# ── Dream Factory wildcard key generation ───────────────────────────────────

DF_KEY_MAP = {
    "woman": "gender", "man": "gender",
    "old": "age", "young": "age", "middle aged": "age",
    "handsome": "appearance", "attractive": "appearance",
    "irish": "ethnicity", "scottish": "ethnicity", "english": "ethnicity",
    "ukrainian": "ethnicity", "russian": "ethnicity", "hungarian": "ethnicity",
    "japanese": "ethnicity", "icelandic": "ethnicity",
    "knight": "character_class", "ranger": "character_class",
    "paladin": "character_class", "barbarian": "character_class",
    "bard": "character_class", "druid": "character_class",
    "rogue": "character_class", "fighter": "character_class",
    "monk": "character_class", "wizard": "character_class", "warlock": "character_class",
    "sitting on the cliff": "pose_setting", "leaning against a tree": "pose_setting",
    "walking in the forest": "pose_setting", "sitting by a river": "pose_setting",
    "walking through a fantasy village": "pose_setting",
    "a moonlit night": "time_of_day", "during the day": "time_of_day",
    "at sunrise": "time_of_day", "at sunset": "time_of_day",
}


def generate_df_wildcard_key(index, values):
    sample = values[0].lower() if values else ""
    for term, key in DF_KEY_MAP.items():
        if term in sample:
            return key
    if len(values) == 1:
        return f"literal_{index:02d}"
    return f"option_{index:02d}"


# ── Main processing ─────────────────────────────────────────────────────────

def process_dream_factory(text, source_name, source_file, dry_run=False):
    """Process Dream Factory format."""
    parsed = parse_dream_factory(text)
    blocks = parsed["prompts_blocks"]

    wildcard_library = {}
    wildcard_refs = []
    template_parts = []

    for i, block in enumerate(blocks):
        cleaned_block = [b.strip() for b in block if b.strip()]
        if not cleaned_block:
            continue
        if len(cleaned_block) == 1:
            single = cleaned_block[0]
            if single.startswith(','):
                template_parts.append(single)
                continue
            if single == "close up of 1":
                template_parts.append("close up portrait of 1")
                continue
            if single in ("descent,", ","):
                template_parts.append(single)
                continue

        key = generate_df_wildcard_key(i, cleaned_block)
        wildcard_library[key] = cleaned_block
        wildcard_refs.append(key)
        template_parts.append("{" + key + "}")

    full_template = " ".join(template_parts)
    full_template = re.sub(r'\s+', ' ', full_template).strip()
    full_template = re.sub(r'\s*,\s*', ', ', full_template)
    full_template = full_template.replace(' ,', ',').replace(',  ', ', ')
    full_template = full_template.strip(', ')
    if not full_template.startswith('{'):
        full_template = full_template[0].upper() + full_template[1:]

    neg_cleaned = parsed["negative_prompt"]
    if neg_cleaned:
        neg_cleaned = re.sub(r'[()\[\]{}]', ' ', neg_cleaned.lower())
        neg_cleaned = re.sub(r':\d+\.\d+', '', neg_cleaned)
        neg_cleaned = re.sub(r'<lora:[^>]+>', '', neg_cleaned)
        neg_cleaned = re.sub(r'\s+', ' ', neg_cleaned).strip()

    metadata = {
        "original_source": source_name,
        "original_prompt": parsed["negative_prompt"],
        "date_added": datetime.datetime.now().isoformat(),
        "source_file": source_file,
        "source_index": 0,
        "dream_factory_settings": parsed["settings"],
        "header_info": parsed["header_info"],
    }

    style_variations = [
        {
            "identifier": "enhanced-prompt",
            "syntax_family": "enhanced-prompt",
            "positive_template": full_template,
            "negative_template": neg_cleaned,
            "negative_prompt_strategy": "weighted",
        },
        {
            "identifier": "comma-separated",
            "syntax_family": "comma-separated",
            "positive_template": full_template,
            "negative_template": neg_cleaned,
            "negative_prompt_strategy": "standard",
        },
    ]

    prompt_entry = {
        "identifier": "fantasy_character_generator_001",
        "concept": "80s-90s fantasy art character generator",
        "status": "active",
        "metadata": metadata,
        "wildcard_refs": wildcard_refs,
        "style_variations": style_variations,
    }

    return wildcard_library, [prompt_entry], []


def process_generic(text, source_name, source_file, fmt, dry_run=False):
    """Process sectioned, structured, or raw formats."""
    # Parse into individual prompts
    if fmt == "sectioned":
        parsed_prompts = parse_sectioned(text)
    elif fmt == "structured":
        parsed_prompts = parse_structured(text)
    else:
        parsed_prompts = parse_raw(text)

    wildcard_library = defaultdict(list)
    prompt_identifiers = []
    rejected = []

    for i, p in enumerate(parsed_prompts):
        positive_raw, negative_raw = extract_negative_prompt(p["raw"])

        metadata = {
            "original_source": source_name,
            "original_prompt": p["raw"],
            "date_added": datetime.datetime.now().isoformat(),
            "source_file": source_file,
            "source_index": i,
        }

        # Check for JSON structure
        is_json, json_data = detect_json_structure(positive_raw)

        # Check for structured fields
        structured_fields = None
        if fmt == "structured":
            concept_line, structured_fields = parse_structured_fields(p["raw"])
            if not concept_line:
                concept_line = positive_raw

        if is_json:
            positive_cleaned = positive_raw.strip()
            metadata["structured_json"] = True
        elif fmt == "structured" and structured_fields:
            positive_cleaned = positive_raw.strip()
        else:
            positive_cleaned = clean_positive_prompt(positive_raw, metadata)

        reject, reason = should_reject_prompt(positive_cleaned, metadata)
        if reject:
            rejected.append({
                "index": i,
                "reason": reason,
                "original": p["raw"][:100],
                "metadata": metadata,
            })
            continue

        if is_json:
            concept = "structured json prompt"
        elif fmt == "structured" and structured_fields:
            concept = concept_line if 'concept_line' in dir() else generate_concept(positive_cleaned)
            if not concept:
                concept = generate_concept(positive_cleaned)
        else:
            concept = generate_concept(positive_cleaned)

        identifier = generate_identifier(concept, i) if not is_json else f"structured_prompt_{i:03d}"

        style_variations = generate_style_variations(
            positive_cleaned, p["raw"],
            is_json=is_json,
            structured_fields=structured_fields,
        )

        prompt_entry = {
            "identifier": identifier,
            "concept": concept,
            "status": "active",
            "metadata": metadata,
            "wildcard_refs": [],
            "style_variations": style_variations,
        }

        prompt_identifiers.append(prompt_entry)

    return dict(wildcard_library), prompt_identifiers, rejected


# ── CLI ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Universal prompt cleaner")
    parser.add_argument("input_file", help="Input file path")
    parser.add_argument("--source", required=True, help="Source name for metadata (e.g., lexica, prompthero)")
    parser.add_argument("--format", choices=["dream_factory", "structured", "sectioned", "raw"],
                        help="Force input format (auto-detected by default)")
    parser.add_argument("--dry-run", "-n", action="store_true", help="Preview without writing files")
    parser.add_argument("--output", help="Output file (default: seeds/<source>_cleaned.json)")
    parser.add_argument("--rejected", help="Rejected file (default: seeds/<source>_rejected.json)")
    args = parser.parse_args()

    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"Error: {input_path} not found")
        sys.exit(1)

    source_name = args.source
    source_file = input_path.name

    with open(input_path, "r") as f:
        text = f.read()

    # Detect or use forced format
    fmt = args.format or detect_format(text)
    print(f"Detected format: {fmt}")

    # Set output paths
    output_path = Path(args.output) if args.output else Path(f"seeds/{source_name}_cleaned.json")
    rejected_path = Path(args.rejected) if args.rejected else Path(f"seeds/{source_name}_rejected.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Process
    if fmt == "dream_factory":
        wildcard_library, prompt_identifiers, rejected = process_dream_factory(
            text, source_name, source_file, dry_run=args.dry_run
        )
    else:
        wildcard_library, prompt_identifiers, rejected = process_generic(
            text, source_name, source_file, fmt, dry_run=args.dry_run
        )

    # Report
    print(f"\nCleaned prompts: {len(prompt_identifiers)}")
    print(f"Rejected prompts: {len(rejected)}")
    print(f"Wildcard categories: {list(wildcard_library.keys())}")

    style_profiles = set()
    for p in prompt_identifiers:
        for sv in p["style_variations"]:
            style_profiles.add(sv["identifier"])
    print(f"Style profiles: {sorted(style_profiles)}")

    if rejected:
        print(f"\nRejected prompts:")
        for r in rejected:
            print(f"  [{r['index']}] {r['reason']}: {r['original'][:60]}...")

    if args.dry_run:
        print("\nDry run - no files written")
        return

    # Write output
    output = {
        "wildcard_library": wildcard_library,
        "prompt_identifiers": prompt_identifiers,
    }
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)

    with open(rejected_path, "w") as f:
        json.dump(rejected, f, indent=2)

    print(f"\nWritten: {output_path}")
    print(f"Written: {rejected_path}")


if __name__ == "__main__":
    main()
