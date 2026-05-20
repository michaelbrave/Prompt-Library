import re
import json
import datetime
from collections import defaultdict

PROMPTHERO_FILE = "PromptHero.txt"
OUTPUT_FILE = "seeds/prompthero_cleaned.json"
REJECTED_FILE = "seeds/prompthero_rejected.json"

MJ_PARAM_PATTERN = re.compile(r'--(?:ar|chaos|stylize|style|stylea|v|q|niji|raw|quality|personalize|profile|s)(?:\s+[\S]+)?', re.IGNORECASE)
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

UNIVERSAL_NEGATIVES = [
    "deformed", "disfigured", "bad anatomy", "bad hands", "poorly drawn hands",
    "poorly drawn face", "mutated", "mutation", "ugly", "duplicate", "morbid",
    "mutilated", "extra limbs", "extra arms", "extra legs", "extra fingers",
    "too many fingers", "fused fingers", "missing fingers", "missing arms",
    "missing legs", "malformed limbs", "gross proportions", "bad proportions",
    "cloned face", "disconnected limbs", "disconnected head", "malformed hands",
    "malformed mouth", "malformed face", "malformed body", "long neck",
    "poorly drawn", "poorly drawn eyes", "poorly drawn iris", "poorly drawn pupils",
    "deformed iris", "deformed pupils", "deformed nose", "deformed face",
    "deformed hands", "deformed feet", "deformed arms", "deformed eyes",
    "deformed irises", "missing hand", "missing limb", "floating limbs",
    "disappearing arms", "disappearing thigh", "disappearing calf", "disappearing legs",
    "fused hand", "huge calf", "abnormal eye proportion", "abnormal hands",
    "abnormal legs", "abnormal feet", "abnormal fingers", "bad body", "bad face",
    "bad teeth", "deformities", "inaccurate body", "inaccurate face",
    "blurry", "blur", "lowres", "low quality", "low detailed", "worst quality",
    "normal quality", "jpeg artifacts", "cropped", "cut off", "out of frame",
    "out of focus", "text", "watermark", "signature", "logo", "autograph",
    "trademark", "username", "title", "censored", "name", "noise",
    "bad art", "bad angle", "bad composition", "boring", "uninteresting",
    "shaved", "underage", "child", "cgi",
    "graphite", "crayon", "impressionist",
    "black and white", "no person visible",
    "nobody visible", "still life", "amputee", "amputation", "incomplete arms",
    "incomplete bra", "malformed clothing", "topless", "broken bra", "fat",
    "obese", "athletic", "muscle tone", "toned muscles", "gym body",
    "porn pose", "arms behind head", "hard penis", "erection",
    "deformed nipples", "deformed vulva", "shaved pussy", "porn star",
    "asian", "ng_deepnegative_v1_75t", "badhandv4",
    "easynegative", "graphic", "glitch", "faultiness",
    "blemish", "wrinkled", "freckled", "umbrella", "distort",
    "animal ear", "mask", "multiple view", "extra hand", "multiple faces",
    "sunglasses", "sitting", "abstract"
]

UNIVERSAL_NEGATIVES_SET = set(UNIVERSAL_NEGATIVES)

STYLE_SPECIFIC_NEGATIVES = {
    "realistic": "anti-realism for stylized/anime prompts",
    "photo": "anti-photo for painting/illustration prompts",
    "photorealistic": "anti-photorealism for stylized prompts",
    "3d": "anti-3d for 2D art prompts",
    "2d": "anti-2d for 3D art prompts",
    "painting": "anti-painting for photo prompts",
    "paintings": "anti-painting for photo prompts",
    "cartoons": "anti-cartoon for realistic prompts",
    "sketch": "anti-sketch for finished art prompts",
    "illustration": "anti-illustration for photo prompts",
    "anime": "anti-anime for realistic prompts",
    "monochrome": "anti-monochrome for color prompts",
    "grayscale": "anti-grayscale for color prompts",
}

LORA_STYLE_MAP = {
    "niji3d": "anime 3D render style, cel-shaded anime aesthetic",
    "edg90hh": "urban streetwear style, edgy fashion",
}


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

        if i + 1 < len(sections) and any(part.startswith(s) for s in ["Midjourney", "Nano", "Flux"]):
            current_section = part.strip().lower().replace(" prompts", "").replace(" prommpts", "").replace(" ", "-")
            i += 1
            continue

        prompts = re.split(r'\n\s*\n', part)
        for p in prompts:
            p = p.strip()
            if p:
                result.append({"raw": p, "section": current_section})

        i += 1

    return result


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


def clean_positive_prompt(text, metadata):
    original = text
    issues = []

    lora_matches = LORA_SYNTAX.findall(text)
    if lora_matches:
        for lora in lora_matches:
            lora_name = lora.split(":")[1].split(">")[0].split(":")[0]
            if lora_name in LORA_STYLE_MAP:
                replacement = LORA_STYLE_MAP[lora_name]
                text = text.replace(lora, f", {replacement}")
                metadata["lora_replaced"] = metadata.get("lora_replaced", []) + [{"name": lora_name, "replaced_with": replacement}]
            else:
                text = LORA_SYNTAX.sub("", text, count=1)
                issues.append(f"removed unknown LoRA: {lora_name}")
                metadata["lora_removed"] = metadata.get("lora_removed", []) + [{"name": lora_name}]

    if MJ_PARAM_PATTERN.search(original):
        metadata["mj_params_removed"] = True
    text = MJ_PARAM_PATTERN.sub("", text)

    def replace_weighted(m):
        return m.group(1)

    text = WEIGHTED_PARENS.sub(replace_weighted, text)
    text = BRACKET_WEIGHT.sub(replace_weighted, text)

    def replace_alt(m):
        return m.group(1)

    text = ALT_SYNTAX.sub(replace_alt, text)

    text = ATTENTION_SYNTAX.sub("", text)

    def replace_brace(m):
        return m.group(1)

    text = DOUBLE_BRACE.sub(replace_brace, text)

    text = MULTI_PARENS.sub(r'\1', text)

    text = TRAILING_DASH.sub("", text)

    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'\s*,\s*', ', ', text)
    text = re.sub(r',\s*,', ',', text)
    text = text.strip().strip(",.")

    if issues:
        metadata["cleaning_issues"] = issues

    return text


def clean_negative_prompt(text):
    if not text:
        return "", []

    universal = []
    style_specific = []

    cleaned_text = text.lower()
    cleaned_text = re.sub(r'[()\[\]{}]', ' ', cleaned_text)
    cleaned_text = re.sub(r'[,\|]', ' ', cleaned_text)

    tokens = [t.strip() for t in cleaned_text.split() if t.strip()]

    found = set()
    i = 0

    while i < len(tokens):
        matched = False

        for length in [4, 3, 2, 1]:
            if i + length <= len(tokens):
                candidate = " ".join(tokens[i:i + length])
                if candidate in UNIVERSAL_NEGATIVES_SET and candidate not in found:
                    universal.append(candidate)
                    found.add(candidate)
                    i += length
                    matched = True
                    break

        if not matched:
            token = tokens[i]
            if token in STYLE_SPECIFIC_NEGATIVES:
                style_specific.append({"term": token, "meaning": STYLE_SPECIFIC_NEGATIVES[token]})
            i += 1

    universal_cleaned = ", ".join(sorted(set(universal))) if universal else ""
    return universal_cleaned, style_specific


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

    if metadata.get("lora_removed") and not metadata.get("lora_replaced"):
        return True, "unknown LoRA removed with no style replacement, prompt likely degraded"

    return False, None


def detect_json_structure(text):
    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, dict):
                return True, parsed
        except json.JSONDecodeError:
            pass
    return False, None


def clean_and_export(filepath):
    with open(filepath, "r") as f:
        text = f.read()

    prompts = split_prompts(text)

    wildcard_library = defaultdict(list)
    prompt_identifiers = []
    rejected = []
    style_profiles_seen = set()

    for i, p in enumerate(prompts):
        positive_raw, negative_raw = extract_negative_prompt(p["raw"])

        metadata = {
            "original_source": p["section"],
            "original_prompt": p["raw"],
            "date_added": datetime.datetime.now().isoformat(),
            "source_file": "PromptHero.txt",
            "source_index": i
        }

        is_json, json_data = detect_json_structure(positive_raw)

        if is_json:
            positive_cleaned = positive_raw.strip()
            metadata["structured_json"] = True
        else:
            positive_cleaned = clean_positive_prompt(positive_raw, metadata)

        reject, reason = should_reject_prompt(positive_cleaned, metadata)
        if reject:
            rejected.append({
                "index": i,
                "reason": reason,
                "original": p["raw"][:100],
                "metadata": metadata
            })
            continue

        negative_cleaned, style_negatives = clean_negative_prompt(negative_raw)

        if style_negatives:
            for sn in style_negatives:
                if sn["term"] not in wildcard_library.get("style_negative", []):
                    wildcard_library["style_negative"].append(sn["term"])
                metadata["style_specific_negatives"] = metadata.get("style_specific_negatives", []) + [sn]

        concept = generate_concept(positive_cleaned) if not is_json else "structured json prompt"
        identifier = generate_identifier(concept, i) if not is_json else f"structured_prompt_{i:03d}"

        style_variations = []

        if is_json:
            style_variations.append({
                "identifier": "lisp-like",
                "syntax_family": "lisp-like",
                "positive_template": positive_cleaned,
                "negative_template": "",
                "negative_prompt_strategy": "structured"
            })
        else:
            style_variations.append({
                "identifier": "comma-separated",
                "syntax_family": "comma-separated",
                "positive_template": positive_cleaned,
                "negative_template": negative_cleaned,
                "negative_prompt_strategy": "standard"
            })

            sentences = re.split(r'[.!?]+', positive_cleaned)
            full_sentences = [s.strip() for s in sentences if len(s.strip()) > 20]
            if len(full_sentences) >= 2:
                style_variations.append({
                    "identifier": "everyday-speech",
                    "syntax_family": "everyday-speech",
                    "positive_template": positive_cleaned,
                    "negative_template": negative_cleaned,
                    "negative_prompt_strategy": "minimal"
                })

            has_weights = bool(re.search(r'\([^)]+:\d+\.\d+\)', positive_raw)) or bool(re.search(r'\[[^:\]]+:\d+\.\d+\]', positive_raw))
            if has_weights:
                style_variations.append({
                    "identifier": "enhanced-prompt",
                    "syntax_family": "enhanced-prompt",
                    "positive_template": positive_cleaned,
                    "negative_template": negative_cleaned,
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

        if style_negatives:
            prompt_entry["wildcard_refs"].append("style_negative")

        prompt_identifiers.append(prompt_entry)
        style_profiles_seen.update(sv["identifier"] for sv in style_variations)

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
    print(f"Style profiles used: {sorted(style_profiles_seen)}")

    if rejected:
        print(f"\nRejected prompts:")
        for r in rejected:
            print(f"  [{r['index']}] {r['reason']}: {r['original'][:60]}...")

    return output, rejected


if __name__ == "__main__":
    output, rejected = clean_and_export(PROMPTHERO_FILE)
