import re
import json
import argparse
from collections import Counter, defaultdict

MJ_PARAMS = re.compile(r'(--(?:ar|chaos|stylize|style|v|q|niji|raw|quality|personalize|profile|s)\s+[\w\.\-]+)', re.IGNORECASE)
WEIGHTED_SYNTAX = re.compile(r'\([^)]+:\d+\.\d+\)')
LORA_SYNTAX = re.compile(r'<lora:[^>]+>')
ALT_SYNTAX = re.compile(r'\[[^\]]+\|[^\]]+\]')
ATTENTION_SYNTAX = re.compile(r'::\d+')
BRACKET_WEIGHT = re.compile(r'\[[^:\]]+:\d+\.\d+\]')
DOUBLE_BRACE = re.compile(r'\{\{[^}]+\}\}')

NEGATIVE_PREFIX = re.compile(r'^(?:Negative prompt|negative prompts)\s*:', re.IGNORECASE)


def split_prompts(text):
    sections = re.split(r'\n###\s+(.+?)\s*\n', text)
    result = []
    current_section = "stable-diffusion"

    i = 0
    while i < len(sections):
        part = sections[i].strip()
        if not part:
            i += 1
            continue

        if i + 1 < len(sections) and (sections[i].startswith("Midjourney") or sections[i].startswith("Nano") or sections[i].startswith("Flux")):
            current_section = sections[i].strip().lower().replace(" prompts", "").replace(" prommpts", "").replace(" ", "-")
            i += 1
            continue

        prompts = re.split(r'\n\s*\n', part)
        for p in prompts:
            p = p.strip()
            if p:
                result.append({
                    "raw": p,
                    "section": current_section
                })

        i += 1

    return result


def detect_style(prompt_text):
    text = prompt_text.strip()

    if text.startswith("{"):
        try:
            json.loads(text)
            return "lisp-like"
        except json.JSONDecodeError:
            pass

    has_mj_params = bool(MJ_PARAMS.search(text))
    has_weighted = bool(WEIGHTED_SYNTAX.search(text)) or bool(BRACKET_WEIGHT.search(text))
    has_lora = bool(LORA_SYNTAX.search(text))
    has_alt = bool(ALT_SYNTAX.search(text))
    has_attention = bool(ATTENTION_SYNTAX.search(text))
    has_double_brace = bool(DOUBLE_BRACE.search(text))

    if has_weighted and not has_mj_params:
        return "enhanced-prompt"

    if has_mj_params:
        if has_weighted:
            return "enhanced-prompt"
        return "comma-separated"

    sentences = re.split(r'[.!?]+', text)
    full_sentences = [s.strip() for s in sentences if len(s.strip()) > 20]
    comma_parts = [p.strip() for p in text.split(",") if p.strip()]

    if len(full_sentences) >= 2:
        return "everyday-speech"

    if has_lora or has_alt or has_attention:
        return "enhanced-prompt"

    if len(comma_parts) > len(full_sentences) * 2:
        return "comma-separated"

    if len(full_sentences) >= 1 and len(comma_parts) < 5:
        return "everyday-speech"

    return "comma-separated"


def extract_negative_prompt(prompt_text):
    lines = prompt_text.split("\n")
    positive_lines = []
    negative_text = None

    for line in lines:
        if NEGATIVE_PREFIX.match(line.strip()):
            negative_text = NEGATIVE_PREFIX.sub("", line.strip()).strip()
        else:
            positive_lines.append(line)

    return "\n".join(positive_lines).strip(), negative_text


def extract_wildcard_candidates(prompt_text):
    candidates = []

    for match in LORA_SYNTAX.finditer(prompt_text):
        candidates.append({"type": "lora", "text": match.group(), "start": match.start(), "end": match.end()})

    for match in WEIGHTED_SYNTAX.finditer(prompt_text):
        candidates.append({"type": "weighted", "text": match.group(), "start": match.start(), "end": match.end()})

    for match in BRACKET_WEIGHT.finditer(prompt_text):
        candidates.append({"type": "bracket_weight", "text": match.group(), "start": match.start(), "end": match.end()})

    for match in ALT_SYNTAX.finditer(prompt_text):
        candidates.append({"type": "alt_syntax", "text": match.group(), "start": match.start(), "end": match.end()})

    for match in ATTENTION_SYNTAX.finditer(prompt_text):
        candidates.append({"type": "attention", "text": match.group(), "start": match.start(), "end": match.end()})

    for match in DOUBLE_BRACE.finditer(prompt_text):
        candidates.append({"type": "double_brace", "text": match.group(), "start": match.start(), "end": match.end()})

    for match in MJ_PARAMS.finditer(prompt_text):
        candidates.append({"type": "mj_param", "text": match.group(), "start": match.start(), "end": match.end()})

    return candidates


def generate_identifier(concept, index):
    words = concept.lower().split()[:4]
    slug = "_".join(re.sub(r'[^a-z0-9]', '', w) for w in words if w)
    if not slug:
        slug = "prompt"
    return f"{slug}_{index:03d}"


def generate_concept(prompt_text, max_words=8):
    text = prompt_text.strip()
    text = MJ_PARAMS.sub("", text)
    text = WEIGHTED_SYNTAX.sub(lambda m: m.group().split(":")[0][1:], text)
    text = LORA_SYNTAX.sub("", text)
    text = re.sub(r'[^a-zA-Z\s]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    words = text.split()[:max_words]
    return " ".join(words) if words else text[:50]


def analyze_file(filepath):
    with open(filepath, "r") as f:
        text = f.read()

    prompts = split_prompts(text)

    style_counts = Counter()
    section_counts = Counter()
    wildcard_type_counts = Counter()
    all_wildcards = defaultdict(list)

    analyzed = []

    for i, p in enumerate(prompts):
        positive, negative = extract_negative_prompt(p["raw"])
        style = detect_style(positive)
        concept = generate_concept(positive)
        identifier = generate_identifier(concept, i)
        wildcards = extract_wildcard_candidates(positive)

        style_counts[style] += 1
        section_counts[p["section"]] += 1

        for wc in wildcards:
            wildcard_type_counts[wc["type"]] += 1
            all_wildcards[wc["type"]].append(wc["text"])

        analyzed.append({
            "index": i,
            "identifier": identifier,
            "concept": concept,
            "section": p["section"],
            "detected_style": style,
            "positive": positive[:100] + "..." if len(positive) > 100 else positive,
            "has_negative": negative is not None,
            "wildcard_count": len(wildcards)
        })

    print(f"Total prompts: {len(prompts)}")
    print(f"\nBy section:")
    for section, count in section_counts.items():
        print(f"  {section}: {count}")

    print(f"\nBy detected style:")
    for style, count in style_counts.items():
        print(f"  {style}: {count}")

    print(f"\nWildcard types found:")
    for wtype, count in wildcard_type_counts.items():
        print(f"  {wtype}: {count}")

    print(f"\nSample prompts by style:")
    for style in style_counts.keys():
        samples = [a for a in analyzed if a["detected_style"] == style][:2]
        print(f"\n  {style}:")
        for s in samples:
            print(f"    [{s['identifier']}] {s['positive'][:80]}...")

    return analyzed, all_wildcards


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Analyze a raw prompt source before cleaning.")
    parser.add_argument("file", help="Prompt source file to inspect")
    args = parser.parse_args()
    analyze_file(args.file)
