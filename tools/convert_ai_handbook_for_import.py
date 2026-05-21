"""
Convert AI Handbook extracted prompts to importable format for the database.
Reads seeds/ai_handbook_cleaned.json → produces seeds/ai_handbook_import.json
"""

import json
import re
import datetime

INPUT_FILE = "seeds/ai_handbook_cleaned.json"
OUTPUT_FILE = "seeds/ai_handbook_import.json"

with open(INPUT_FILE, "r", encoding="utf-8") as f:
    prompts = json.load(f)

def generate_identifier(concept, index):
    words = concept.lower().split()[:4]
    slug = "_".join(re.sub(r'[^a-z0-9]', '', w) for w in words if w)
    if not slug:
        slug = "prompt"
    return f"ai_handbook_{slug}_{index:03d}"

def generate_concept(prompt_text, max_words=8):
    text = prompt_text.strip()
    text = re.sub(r'--\w+(?:\s+[\w\.\-]+)?', '', text)
    text = re.sub(r'[^a-zA-Z\s]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    words = text.split()[:max_words]
    return " ".join(words) if words else text[:50]

def detect_syntax(positive):
    has_mj_params = bool(re.search(r'--\w+', positive))
    sentences = re.split(r'[.!?]+', positive)
    full_sentences = [s.strip() for s in sentences if len(s.strip()) > 20]
    comma_parts = [p.strip() for p in positive.split(",") if p.strip()]
    if len(full_sentences) >= 2:
        return "everyday-speech"
    if has_mj_params:
        return "comma-separated"
    if len(comma_parts) > len(full_sentences) * 2:
        return "comma-separated"
    return "everyday-speech"

prompt_identifiers = []

for i, p in enumerate(prompts):
    title = p.get("title", "")
    prompt_text = p.get("prompt", "")
    platform = p.get("platform", "")
    category = p.get("category", "")
    source = p.get("source", "The AI Handbook for Everyone")

    concept = generate_concept(prompt_text)
    identifier = generate_identifier(concept, i)

    syntax_family = detect_syntax(prompt_text)

    prompt_entry = {
        "identifier": identifier,
        "concept": concept,
        "status": "active",
        "metadata": {
            "original_source": source,
            "original_prompt": prompt_text,
            "date_added": datetime.datetime.now().isoformat(),
            "source_file": "ai_handbook_book.txt",
            "source_index": i,
            "title": title,
            "platform": platform,
            "category": category
        },
        "wildcard_refs": [],
        "style_variations": [
            {
                "identifier": syntax_family,
                "syntax_family": syntax_family,
                "negative_prompt_strategy": "minimal",
                "positive_template": prompt_text,
                "negative_template": ""
            }
        ]
    }
    prompt_identifiers.append(prompt_entry)

output = {
    "wildcard_library": {},
    "prompt_identifiers": prompt_identifiers
}

with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    json.dump(output, f, indent=2, ensure_ascii=False)

print(f"Converted {len(prompt_identifiers)} prompts")
print(f"Output: {OUTPUT_FILE}")
