"""
Extract SDXL prompts from "Top 40 useful prompts for Stable Diffusion XL"
Produces import-ready JSON for the database.
"""

import re
import json
import datetime

INPUT_FILE = "sdxl_top40_prompts.txt"
OUTPUT_FILE = "seeds/sdxl_top40_import.json"

with open(INPUT_FILE, "r", encoding="utf-8") as f:
    lines = f.readlines()

CATEGORY_HEADERS = {"Photographic", "Stylized", "Design", "Other prompts"}
CATEGORY_MAP = {
    "Photographic": "Photorealistic",
    "Stylized": "Stylized",
    "Design": "Design",
    "Other prompts": "General"
}

current_category = "General"
prompts = []

def clean_line(l):
    return l.strip()

for line in lines:
    stripped = clean_line(line)
    if not stripped:
        continue

    # Skip page numbers like "13/44"
    if re.match(r'^\d+/\d+$', stripped):
        continue

    # Skip known non-prompt lines
    skip_prefixes = [
        "Daria Wind", "Top 40 useful prompts", "medium.com/", "PHYGITAL+",
        "Top highlight", "In this brief article", "Important note:",
        "Images down below", "For creating images", "In generations",
        "For more vibrant", "Join Medium", "Remember me",
        "Tip:", "We will soon", "Subscribe to", "1/44", "2/44"
    ]
    if any(stripped.startswith(p) for p in skip_prefixes):
        continue

    # Skip lines that are just metadata about models/usage
    if ("using" in stripped and "suggest" in stripped) or \
       ("DreamShaper" in stripped and "Mohawk" in stripped) or \
       ("JuggerNaut" in stripped and "DreamShaper" in stripped):
        continue

    # Check for category headers
    if stripped in CATEGORY_HEADERS:
        current_category = CATEGORY_MAP.get(stripped, "General")
        continue

    # Check for prompt pattern: #N. Title: text
    prompt_match = re.match(r'^#(\d+)\.\s*(.+?):\s*(.*)', stripped)
    if prompt_match:
        num = prompt_match.group(1)
        title = prompt_match.group(2).strip()
        text = prompt_match.group(3).strip()
        prompts.append({
            "num": int(num),
            "title": title,
            "text": text,
            "category": current_category,
            "platform": "Stable Diffusion XL"
        })
    else:
        # Continuation of previous prompt's text
        if prompts:
            prompts[-1]["text"] += " " + stripped

# Clean up: normalize whitespace
for p in prompts:
    p["text"] = re.sub(r'\s+', ' ', p["text"].strip())

print(f"Extracted {len(prompts)} prompts")

# ── Convert to import format ──

def generate_identifier(concept, index):
    words = concept.lower().split()[:4]
    slug = "_".join(re.sub(r'[^a-z0-9]', '', w) for w in words if w)
    if not slug:
        slug = "prompt"
    return f"sdxl_top40_{slug}_{index:03d}"

def generate_concept(prompt_text, max_words=8):
    text = prompt_text.strip()
    text = re.sub(r'--\w+(?:\s+[\w\.\-]+)?', '', text)
    text = re.sub(r'[^a-zA-Z\s]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    words = text.split()[:max_words]
    return " ".join(words) if words else text[:50]

def detect_syntax(positive):
    sentences = re.split(r'[.!?]+', positive)
    full_sentences = [s.strip() for s in sentences if len(s.strip()) > 20]
    comma_parts = [p.strip() for p in positive.split(",") if p.strip()]
    if len(full_sentences) >= 2:
        return "everyday-speech"
    if len(comma_parts) > len(full_sentences) * 2:
        return "comma-separated"
    return "comma-separated"

prompt_identifiers = []

for i, p in enumerate(prompts):
    prompt_text = p["text"]
    title = p["title"]
    category = p["category"]
    platform = p["platform"]

    concept = generate_concept(prompt_text)
    identifier = generate_identifier(concept, i)
    syntax_family = detect_syntax(prompt_text)

    prompt_entry = {
        "identifier": identifier,
        "concept": concept,
        "status": "active",
        "metadata": {
            "original_source": "medium.com - Top 40 useful prompts for Stable Diffusion XL",
            "original_prompt": prompt_text,
            "date_added": datetime.datetime.now().isoformat(),
            "source_file": "sdxl_top40_prompts.txt",
            "source_index": i,
            "title": f"SDXL #{p['num']}: {title}",
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

print(f"Output: {OUTPUT_FILE}")
print(f"Imported count: {len(prompt_identifiers)}")
