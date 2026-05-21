"""
Extract 30 Stable Diffusion prompts from cyberlink.com article.
Produces import-ready JSON for the database.
"""

import re
import json
import datetime

INPUT_FILE = "sd30_prompts.txt"
OUTPUT_FILE = "seeds/sd30_import.json"

with open(INPUT_FILE, "r", encoding="utf-8") as f:
    text = f.read()

SECTION_CATEGORY = {
    "Text-to-Image AI Prompts": "Text-to-Image",
    "Image-to-Image AI Prompts": "Image-to-Image",
    "Inpainting AI Prompts": "Inpainting",
    "Outpainting AI Prompts": "Outpainting",
}

# ── Split into sections by the header markers ──
# Find all section headers and their positions
section_starts = []
for header, cat in SECTION_CATEGORY.items():
    idx = text.find(header)
    if idx >= 0:
        section_starts.append((idx, header, cat))

section_starts.sort()
sections = []
for i, (idx, header, cat) in enumerate(section_starts):
    end = section_starts[i+1][0] if i+1 < len(section_starts) else len(text)
    sections.append((cat, text[idx:end]))

# ── Extract prompts from each section ──
# Pattern: "N. Title\n...Prompt sample: \"...\""
# The prompt text can span multiple lines
prompt_header = re.compile(r'^(\d+)\.\s*(.+)$', re.MULTILINE)
prompt_sample = re.compile(r'Prompt sample:\s*"([^"]*?)"', re.DOTALL)

entries = []

for cat, section_text in sections:
    # Find all prompt headers with their positions
    headers = list(prompt_header.finditer(section_text))
    samples = list(prompt_sample.finditer(section_text))

    # For each sample, find the closest preceding header
    for sample_match in samples:
        sample_start = sample_match.start()
        # Find the last header before this sample
        best_header = None
        for h in headers:
            if h.start() < sample_start:
                best_header = h
            else:
                break
        if best_header:
            num = int(best_header.group(1))
            title = best_header.group(2).strip()
            prompt_text = sample_match.group(1).strip()
            # Clean up: normalize whitespace
            prompt_text = re.sub(r'\s+', ' ', prompt_text)
            entries.append({
                "num": num,
                "title": title,
                "text": prompt_text,
                "category": cat
            })

# Sort by number
entries.sort(key=lambda e: e["num"])
print(f"Extracted {len(entries)} prompts")

# ── Build import JSON ──────────────────────────────────────────────

def generate_identifier(concept, index):
    words = concept.lower().split()[:4]
    slug = "_".join(re.sub(r'[^a-z0-9]', '', w) for w in words if w)
    if not slug:
        slug = "prompt"
    return f"sd30_{slug}_{index:03d}"

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
for i, p in enumerate(entries):
    prompt_text = p["text"]
    concept = generate_concept(prompt_text)
    identifier = generate_identifier(concept, i)
    syntax_family = detect_syntax(prompt_text)

    prompt_entry = {
        "identifier": identifier,
        "concept": concept,
        "status": "active",
        "metadata": {
            "original_source": "cyberlink.com - 30 Stable Diffusion Prompt Examples",
            "original_prompt": prompt_text,
            "date_added": datetime.datetime.now().isoformat(),
            "source_file": "sd30_prompts.txt",
            "source_index": i,
            "title": f"SD #{p['num']}: {p['title']}",
            "platform": "Stable Diffusion",
            "category": p["category"]
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
print(f"Prompts: {len(prompt_identifiers)}")
cats = {}
for p in prompt_identifiers:
    cat = p["metadata"]["category"]
    cats[cat] = cats.get(cat, 0) + 1
print(f"Categories: {cats}")
