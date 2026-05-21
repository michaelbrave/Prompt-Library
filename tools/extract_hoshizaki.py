#!/usr/bin/env python3
"""Extract prompts from the Hoshizaki book format - v2."""
import re
import json
import sys
sys.path.insert(0, '/var/home/mike/Desktop/Prompt-Library/Prompt-Library')

from clean_prompts import clean_positive_prompt, should_reject_prompt, generate_concept, generate_identifier, generate_style_variations

SOURCE = "hoshizaki_book"
SOURCE_FILE = "hoshizaki_book.txt"

with open('/var/home/mike/Desktop/Prompt-Library/Prompt-Library/hoshizaki_book.txt', 'r') as f:
    text = f.read()

ex1_positions = [m.start() for m in re.finditer(r'^Example 1:', text, re.MULTILINE)]
final_positions = [m.start() for m in re.finditer(r'^Final Thoughts', text, re.MULTILINE)]

start = ex1_positions[1]
end = final_positions[-1] + 200
main_body = text[start:end]

examples_raw = re.split(r'\n(?=Example \d+:)', main_body)
main_examples = [e for e in examples_raw if len(e.strip()) > 500]

print(f"Processing {len(main_examples)} example sections\n")


def extract_prompts_from_example(ex_text):
    """Extract prompt blocks from an example section, excluding ADetailer sub-prompts."""
    results = []
    lines = ex_text.split('\n')
    i = 0
    in_adetailer = False

    while i < len(lines):
        line = lines[i].strip()

        # Track ADetailer section boundaries
        if re.match(r'^ADetailer', line):
            in_adetailer = True
            i += 1
            continue

        if re.match(r'^Example \d+:', line):
            in_adetailer = False
            i += 1
            continue

        if re.match(r'^Prompt\s*$', line) and not in_adetailer:
            prompt_lines = []
            i += 1
            while i < len(lines):
                next_line = lines[i].strip()

                if next_line == "Prompt":
                    break

                end_markers = ["Negative Prompt", "Parameters and Data", "Parameter",
                               "Pameter", "Same as above", "Paramater", "Paramater and Data"]
                if next_line in end_markers:
                    break
                if next_line == "":
                    la = i + 1
                    while la < len(lines) and lines[la].strip() == "":
                        la += 1
                    if la < len(lines) and lines[la].strip() in end_markers:
                        break

                if next_line.startswith("`"):
                    i += 1
                    continue

                prompt_lines.append(lines[i])
                i += 1

            prompt_text = '\n'.join(prompt_lines).strip()
            if prompt_text and len(prompt_text) > 20:
                results.append({'type': 'positive', 'text': prompt_text})
            continue

        if line in ("Same as above", "Same as above ") and not in_adetailer:
            results.append({'type': 'same_as_above', 'text': ''})
            i += 1
            continue

        if line.startswith("Negative Prompt") and not in_adetailer:
            neg_lines = []
            i += 1
            while i < len(lines):
                next_line = lines[i].strip()

                end_markers = ["Parameters and Data", "Parameter", "Pameter",
                               "Upscale", "ADetailer", "Paramater", "Paramater and Data"]
                if next_line in end_markers:
                    break

                if next_line == "N/A":
                    neg_lines.append("")
                    i += 1
                    break

                if next_line == "":
                    la = i + 1
                    while la < len(lines) and lines[la].strip() == "":
                        la += 1
                    if la < len(lines) and lines[la].strip() in end_markers:
                        break

                if re.match(r'^(worst|bad|lowres|anime_style|sketch|censored|watermark|signature|unaestheticXL)',
                           next_line, re.IGNORECASE):
                    pass

                neg_lines.append(lines[i])
                i += 1

            neg_text = '\n'.join(neg_lines).strip()
            if neg_text:
                for r in reversed(results):
                    if r['type'] == 'positive' and 'negative' not in r:
                        r['negative'] = neg_text
                        break
            continue

        i += 1

    return [r for r in results if r['type'] == 'positive']


all_prompts = []
all_rejected = []

for idx, ex in enumerate(main_examples):
    ex = ex.strip()
    if not ex:
        continue

    title_match = re.match(r'^(Example \d+:.*?)(?:\n|$)', ex)
    title = title_match.group(1).strip() if title_match else f"Example {idx}"

    prompts = extract_prompts_from_example(ex)

    for p_idx, p in enumerate(prompts):
        raw_text = p['text']
        neg_text = p.get('negative', '')

        metadata = {
            'original_source': SOURCE,
            'source_file': SOURCE_FILE,
            'example': title,
            'prompt_index': p_idx,
            'date_added': '2025-05-21',
        }

        positive_cleaned = clean_positive_prompt(raw_text, metadata)

        reject, reason = should_reject_prompt(positive_cleaned, metadata)
        if reject:
            all_rejected.append({
                'index': len(all_prompts),
                'reason': reason,
                'title': title,
                'original': raw_text[:100],
                'metadata': metadata,
            })
            continue

        concept = generate_concept(positive_cleaned)
        identifier = generate_identifier(concept, idx * 10 + p_idx)

        full_raw = raw_text
        if neg_text:
            full_raw += f"\nNegative Prompt: {neg_text}"

        style_variations = generate_style_variations(positive_cleaned, full_raw)

        if neg_text and style_variations:
            style_variations[0]['negative_template'] = neg_text

        prompt_entry = {
            'identifier': identifier,
            'concept': concept,
            'status': 'active',
            'metadata': metadata,
            'wildcard_refs': [],
            'style_variations': style_variations,
        }

        all_prompts.append(prompt_entry)

print(f"Extracted {len(all_prompts)} prompts")
print(f"Rejected {len(all_rejected)}")

for p in all_prompts:
    print(f"\n  [{p['identifier']}] ({p['metadata']['example']})")
    for sv in p['style_variations']:
        print(f"    [{sv['identifier']}] {sv['positive_template'][:120]}...")
        if sv.get('negative_template'):
            print(f"      Neg: {sv['negative_template'][:100]}...")

if all_rejected:
    print(f"\n\nRejected prompts:")
    for r in all_rejected[:20]:
        print(f"  [{r['index']}] {r['reason']}: {r['title']}: {r['original'][:60]}...")

output = {'wildcard_library': {}, 'prompt_identifiers': all_prompts}

with open('/var/home/mike/Desktop/Prompt-Library/Prompt-Library/seeds/hoshizaki_book_cleaned.json', 'w') as f:
    json.dump(output, f, indent=2)

with open('/var/home/mike/Desktop/Prompt-Library/Prompt-Library/seeds/hoshizaki_book_rejected.json', 'w') as f:
    json.dump(all_rejected, f, indent=2)

print(f"\n\nWritten: seeds/hoshizaki_book_cleaned.json")
print(f"Written: seeds/hoshizaki_book_rejected.json")
