import re
import json
import datetime
from collections import defaultdict

DREAMFACTORY_FILE = "character-generator.prompts"
OUTPUT_FILE = "seeds/character_generator_cleaned.json"
REJECTED_FILE = "seeds/character_generator_rejected.json"

CONFIG_PATTERN = re.compile(r'\[config\]', re.IGNORECASE)
PROMPTS_PATTERN = re.compile(r'\[prompts\]', re.IGNORECASE)
SETTING_PATTERN = re.compile(r'^!(\w+)\s*=\s*(.+)$', re.MULTILINE)
NEG_PROMPT_PATTERN = re.compile(r'^!NEG_PROMPT\s*=\s*(.+)$', re.MULTILINE)


def parse_dreamfactory(filepath):
    with open(filepath, 'r') as f:
        content = f.read()

    header_lines = []
    config_block = ""
    prompts_blocks = []

    current_section = "header"
    current_prompts = []

    for line in content.split('\n'):
        stripped = line.strip()

        if not stripped or stripped.startswith('#'):
            if current_section == "header":
                header_lines.append(stripped)
            continue

        if CONFIG_PATTERN.match(stripped):
            current_section = "config"
            continue

        if PROMPTS_PATTERN.match(stripped):
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
    for match in SETTING_PATTERN.finditer(config_block):
        settings[match.group(1)] = match.group(2).strip()

    neg_prompt = ""
    neg_match = NEG_PROMPT_PATTERN.search(config_block)
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
        "prompts_blocks": prompts_blocks
    }


def build_template_and_wildcards(parsed):
    blocks = parsed["prompts_blocks"]
    wildcard_keys = []
    template_parts = []

    for i, block in enumerate(blocks):
        if len(block) == 1 and not block[0].startswith(','):
            key = f"block_{i:02d}"
            wildcard_keys.append(key)
            template_parts.append("{" + key + "}")
        elif all(item.strip().startswith(',') or item.strip() == '' for item in block):
            for item in block:
                template_parts.append(item.strip())
        else:
            key = f"block_{i:02d}"
            wildcard_keys.append(key)
            template_parts.append("{" + key + "}")

    full_template = " ".join(template_parts)
    full_template = re.sub(r'\s+', ' ', full_template).strip()

    return full_template, wildcard_keys


def generate_wildcard_key(index, values):
    sample = values[0].lower() if values else ""

    key_map = {
        "woman": "gender",
        "man": "gender",
        "old": "age",
        "young": "age",
        "middle aged": "age",
        "handsome": "appearance",
        "attractive": "appearance",
        "irish": "ethnicity",
        "scottish": "ethnicity",
        "english": "ethnicity",
        "ukrainian": "ethnicity",
        "russian": "ethnicity",
        "hungarian": "ethnicity",
        "japanese": "ethnicity",
        "icelandic": "ethnicity",
        "knight": "character_class",
        "ranger": "character_class",
        "paladin": "character_class",
        "barbarian": "character_class",
        "bard": "character_class",
        "druid": "character_class",
        "rogue": "character_class",
        "fighter": "character_class",
        "monk": "character_class",
        "wizard": "character_class",
        "warlock": "character_class",
        "sitting on the cliff": "pose_setting",
        "leaning against a tree": "pose_setting",
        "walking in the forest": "pose_setting",
        "sitting by a river": "pose_setting",
        "walking through a fantasy village": "pose_setting",
        "a moonlit night": "time_of_day",
        "during the day": "time_of_day",
        "at sunrise": "time_of_day",
        "at sunset": "time_of_day",
    }

    for term, key in key_map.items():
        if term in sample:
            return key

    if len(values) == 1:
        return f"literal_{index:02d}"

    return f"option_{index:02d}"


def clean_negative_prompt(neg_text):
    if not neg_text:
        return "", []

    universal = [
        "worst quality", "bad art", "bad design", "lowres", "low quality",
        "monotone", "greyscale", "deformed", "ugly", "normal quality", "average",
        "bad proportions", "bad anatomy", "bad composition",
        "awkward pose", "unrealistic pose",
        "bad hands", "ugly hands", "broken hands", "deformed hands", "inverted hands",
        "extra hands", "missing hands", "bad arms", "ugly arms", "broken arms",
        "deformed arms", "inverted arms", "extra arms", "missing arms",
        "bad fingers", "ugly fingers", "broken fingers", "deformed fingers",
        "extra fingers", "missing fingers", "6 fingers",
        "bad legs", "ugly legs", "broken legs", "deformed legs", "extra legs", "missing legs",
        "bad feet", "ugly feet", "broken feet", "deformed feet", "extra feet", "missing feet",
        "EasyNegative", "anime_badhandv4", "bad-hands-5",
        "interlaced hands", "disconnected collar", "detached collar",
        "bright colors", "extra long hair", "contrast",
        "multi-colored armor", "multi-colored clothing",
        "underexposed", "large moon", "tiny moon",
    ]

    style_specific = {
        "galaxy": "anti-galaxy theme",
        "photorealistic": "anti-photorealism for fantasy art",
    }

    cleaned = neg_text.lower()
    cleaned = re.sub(r'[()\[\]{}]', ' ', cleaned)
    cleaned = re.sub(r':\d+\.\d+', '', cleaned)
    cleaned = re.sub(r'<lora:[^>]+>', '', cleaned)

    found_universal = []
    found_style = []

    for term in universal:
        if term.lower() in cleaned:
            found_universal.append(term)

    for term, meaning in style_specific.items():
        if term.lower() in cleaned:
            found_style.append({"term": term, "meaning": meaning})

    return ", ".join(sorted(set(found_universal))), found_style


def clean_and_export(filepath):
    parsed = parse_dreamfactory(filepath)

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
            if single == "descent,":
                template_parts.append("descent,")
                continue
            if single == ",":
                template_parts.append(",")
                continue

        if len(cleaned_block) == 1 and not cleaned_block[0].startswith(','):
            key = generate_wildcard_key(i, cleaned_block)
            wildcard_library[key] = cleaned_block
            wildcard_refs.append(key)
            template_parts.append("{" + key + "}")
        elif all(item.startswith(',') for item in cleaned_block):
            template_parts.append(cleaned_block[0])
        else:
            key = generate_wildcard_key(i, cleaned_block)
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

    neg_cleaned, style_negs = clean_negative_prompt(parsed["negative_prompt"])

    metadata = {
        "original_source": "dream_factory",
        "original_prompt": parsed["negative_prompt"],
        "date_added": datetime.datetime.now().isoformat(),
        "source_file": "character-generator.prompts",
        "source_index": 0,
        "dream_factory_settings": parsed["settings"],
        "header_info": parsed["header_info"],
        "style_specific_negatives": style_negs
    }

    style_variations = []

    style_variations.append({
        "identifier": "enhanced-prompt",
        "syntax_family": "enhanced-prompt",
        "positive_template": full_template,
        "negative_template": neg_cleaned,
        "negative_prompt_strategy": "weighted"
    })

    style_variations.append({
        "identifier": "comma-separated",
        "syntax_family": "comma-separated",
        "positive_template": full_template,
        "negative_template": neg_cleaned,
        "negative_prompt_strategy": "standard"
    })

    prompt_entry = {
        "identifier": "fantasy_character_generator_001",
        "concept": "80s-90s fantasy art character generator",
        "status": "active",
        "metadata": metadata,
        "wildcard_refs": wildcard_refs,
        "style_variations": style_variations
    }

    wildcard_library_clean = {}
    for key, values in wildcard_library.items():
        wildcard_library_clean[key] = values

    output = {
        "wildcard_library": wildcard_library_clean,
        "prompt_identifiers": [prompt_entry]
    }

    with open(OUTPUT_FILE, "w") as f:
        json.dump(output, f, indent=2)

    print(f"Prompt: {prompt_entry['identifier']}")
    print(f"Concept: {prompt_entry['concept']}")
    print(f"Wildcard refs: {wildcard_refs}")
    print(f"Template: {full_template[:120]}...")
    print(f"Negative: {neg_cleaned[:80]}...")
    print(f"Style negatives: {style_negs}")
    print(f"\nWildcard categories:")
    for key, values in wildcard_library.items():
        print(f"  {key}: {len(values)} values - {values[:3]}{'...' if len(values) > 3 else ''}")

    return output


if __name__ == "__main__":
    output = clean_and_export(DREAMFACTORY_FILE)
