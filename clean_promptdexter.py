import re
import json
import datetime
from collections import defaultdict

PROMPTDEXTER_FILE = "promptdexter.txt"
OUTPUT_FILE = "seeds/promptdexter_cleaned.json"
REJECTED_FILE = "seeds/promptdexter_rejected.json"

KNOWN_FIELDS = [
    "Subject", "Clothing", "Action", "Environment", "Camera",
    "Lighting", "Objects", "Style Details", "Hair", "Accessories"
]

FIELD_PATTERN = re.compile(
    r'^(' + '|'.join(KNOWN_FIELDS) + r')\s*:\s*(.+)$',
    re.IGNORECASE
)


def split_prompts(text):
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

    return prompts


def parse_structured_prompt(text):
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


def generate_identifier(concept, index):
    words = concept.lower().split()[:4]
    slug = "_".join(re.sub(r'[^a-z0-9]', '', w) for w in words if w)
    if not slug:
        slug = "prompt"
    return f"{slug}_{index:03d}"


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


def clean_and_export(filepath):
    with open(filepath, "r") as f:
        text = f.read()

    raw_prompts = split_prompts(text)

    wildcard_library = defaultdict(list)
    prompt_identifiers = []
    rejected = []

    for i, raw in enumerate(raw_prompts):
        concept, fields = parse_structured_prompt(raw)

        if not concept or len(concept.strip()) < 10:
            rejected.append({
                "index": i,
                "reason": "no concept line or too short",
                "original": raw[:100]
            })
            continue

        if not fields:
            rejected.append({
                "index": i,
                "reason": "no structured fields found",
                "original": raw[:100]
            })
            continue

        metadata = {
            "original_source": "promptdexter",
            "original_prompt": raw,
            "date_added": datetime.datetime.now().isoformat(),
            "source_file": "promptdexter.txt",
            "source_index": i,
            "structured_fields": fields,
            "field_keys_present": list(fields.keys())
        }

        identifier = generate_identifier(concept, i)

        style_variations = []

        structured_positive = raw.strip()
        style_variations.append({
            "identifier": "structured-fields",
            "syntax_family": "structured-fields",
            "positive_template": structured_positive,
            "negative_template": "",
            "negative_prompt_strategy": "structured"
        })

        comma_positive = fields_to_comma_separated(fields)
        style_variations.append({
            "identifier": "comma-separated",
            "syntax_family": "comma-separated",
            "positive_template": comma_positive,
            "negative_template": "",
            "negative_prompt_strategy": "standard"
        })

        speech_positive = fields_to_everyday_speech(fields, concept)
        style_variations.append({
            "identifier": "everyday-speech",
            "syntax_family": "everyday-speech",
            "positive_template": speech_positive,
            "negative_template": "",
            "negative_prompt_strategy": "minimal"
        })

        enhanced_positive = fields_to_enhanced(fields, concept)
        style_variations.append({
            "identifier": "enhanced-prompt",
            "syntax_family": "enhanced-prompt",
            "positive_template": enhanced_positive,
            "negative_template": "",
            "negative_prompt_strategy": "weighted"
        })

        prompt_entry = {
            "identifier": identifier,
            "concept": concept,
            "status": "active",
            "metadata": metadata,
            "wildcard_refs": [],
            "style_variations": style_variations
        }

        prompt_identifiers.append(prompt_entry)

    output = {
        "wildcard_library": {k: list(v) for k, v in wildcard_library.items()},
        "prompt_identifiers": prompt_identifiers
    }

    with open(OUTPUT_FILE, "w") as f:
        json.dump(output, f, indent=2)

    with open(REJECTED_FILE, "w") as f:
        json.dump(rejected, f, indent=2)

    print(f"Cleaned prompts: {len(prompt_identifiers)}")
    print(f"Rejected prompts: {len(rejected)}")
    print(f"Wildcard categories: {list(wildcard_library.keys())}")
    print(f"Style profiles used: structured-fields, comma-separated, everyday-speech, enhanced-prompt")

    if rejected:
        print(f"\nRejected prompts:")
        for r in rejected:
            print(f"  [{r['index']}] {r['reason']}: {r['original'][:60]}...")

    all_field_keys = set()
    for p in prompt_identifiers:
        all_field_keys.update(p['metadata']['field_keys_present'])
    print(f"\nField keys found across all prompts: {sorted(all_field_keys)}")

    return output, rejected


if __name__ == "__main__":
    output, rejected = clean_and_export(PROMPTDEXTER_FILE)
