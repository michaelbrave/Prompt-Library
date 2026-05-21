"""
Extract image generation prompts from "The AI Handbook for Everyone"
Sources:
  - Chapter 5: Ideogram (20 prompts: 10 fantasy/scifi + 10 sales/marketing)
  - Chapter 6: Canva Magic Media (11 prompts: 5 video + 6 image)
  - Chapter 7: DALL-E 2 (10 business graphics prompts)
  - Chapter 8: MidJourney (10 sample prompts)
Output: JSON file compatible with clean_prompts.py
"""

import re
import json

INPUT_FILE = "ai_handbook_book.txt"
OUTPUT_FILE = "seeds/ai_handbook_cleaned.json"
REJECTED_FILE = "seeds/ai_handbook_rejected.json"

with open(INPUT_FILE, "r", encoding="utf-8") as f:
    text = f.read()

prompts = []
rejected = []

def add(title, prompt_text, platform, category):
    prompts.append({
        "title": title,
        "prompt": prompt_text.strip(),
        "platform": platform,
        "category": category,
        "source": "The AI Handbook for Everyone"
    })

# ── Chapter 5: Ideogram — 10 Fantasy/Sci-Fi (lines 724-744) ──
# Pattern: "N. Title\nPrompt:\"...\""
ideogram_fantasy_section = text.split("Ten Example Prompts for Stunning AI Images")[1] \
    if "Ten Example Prompts for Stunning AI Images" in text else ""
ideogram_fantasy_section = ideogram_fantasy_section.split("Ten Example Prompts for Sales")[0] \
    if "Ten Example Prompts for Sales" in ideogram_fantasy_section else ""

# Parse numbered entries: "N. Title\nPrompt:\"content\""
pattern = r'(\d+)\.\s*(.+?)\n\s*Prompt:\s*"([^"]+)"'
for m in re.finditer(pattern, ideogram_fantasy_section, re.DOTALL):
    num, title, prompt_text = m.groups()
    add(f"Ideogram Fantasy #{num}: {title.strip()}", prompt_text, "Ideogram", "Fantasy/Sci-Fi")

# ── Chapter 5: Ideogram — 10 Sales & Marketing (lines 745-765) ──
ideogram_sales_section = text.split("Ten Example Prompts for Sales")[1] \
    if "Ten Example Prompts for Sales" in text else ""
ideogram_sales_section = ideogram_sales_section.split("Thirty Advanced Commands")[0] \
    if "Thirty Advanced Commands" in ideogram_sales_section else ""

for m in re.finditer(pattern, ideogram_sales_section, re.DOTALL):
    num, title, prompt_text = m.groups()
    add(f"Ideogram Sales #{num}: {title.strip()}", prompt_text, "Ideogram", "Sales & Marketing")

# ── Chapter 6: Canva Magic Media — Video Prompts (lines 893-897) ──
# Pattern: "Title: description" (first entry lacks number) "N. Title: description" (rest)
canva_video_section = text.split("Five Sample Magic Media Prompts You Can Build On")[1] \
    if "Five Sample Magic Media Prompts You Can Build On" in text else ""
canva_video_section = canva_video_section.split("Six Magic Media Prompts")[0] \
    if "Six Magic Media Prompts" in canva_video_section else ""

# Split by lines starting with a number or a known title
canva_video_lines = [l.strip() for l in canva_video_section.split("\n") if l.strip()]
video_num = 1
for line in canva_video_lines:
    # Remove leading number prefix if present
    line = re.sub(r'^\d+\.\s*', '', line)
    colon_pos = line.find(":")
    if colon_pos > 0:
        title = line[:colon_pos].strip()
        desc = line[colon_pos+1:].strip()
        add(f"Canva Magic Media Video #{video_num}: {title}", desc, "Canva Magic Media", "Video")
        video_num += 1

# ── Chapter 6: Canva Magic Media — Image Prompts (lines 898-911) ──
canva_img_section = text.split("Six Magic Media Prompts to Generate Business Related Images")[1] \
    if "Six Magic Media Prompts to Generate Business Related Images" in text else ""
canva_img_section = canva_img_section.split("Exploring Canva Pro Features")[0] \
    if "Exploring Canva Pro Features" in canva_img_section else ""

# Parse: numbered title, then next line is the prompt
img_lines = [l.strip() for l in canva_img_section.split("\n") if l.strip()]
i = 0
while i < len(img_lines):
    line = img_lines[i]
    m = re.match(r'(\d+)\.\s*(.*)', line)
    if m:
        num = m.group(1)
        title = m.group(2).strip()
        # Next non-empty line is the prompt
        if i + 1 < len(img_lines) and not re.match(r'\d+\.', img_lines[i+1]):
            prompt_text = img_lines[i+1]
            i += 2
        else:
            prompt_text = title
            i += 1
        add(f"Canva Magic Media Image #{num}: {title}", prompt_text, "Canva Magic Media", "Business Image")
    else:
        i += 1

# ── Chapter 7: DALL-E 2 — 10 Business Graphics (line 954) ──
# All on one truncated line, format: "Category: \"prompt.\" Regular Edit: \"...\" Inpainting Edit: \"...\""
# or just "Category: \"prompt.\""
dalle_section = text.split("10 Example Prompts for Business Graphics")[1] \
    if "10 Example Prompts for Business Graphics" in text else ""
dalle_section = dalle_section.split("Tips for Success")[0] \
    if "Tips for Success" in dalle_section else ""

# Parse out "Category: \"prompt\"" patterns - extract the main prompt before any edit
dalle_pattern = re.findall(r'([A-Za-z ]+?):\s*"([^"]+)"', dalle_section)
seen_titles = set()
for cat, prompt_text in dalle_pattern:
    cat = cat.strip()
    # Skip edit instructions and non-category entries
    if cat in ("Regular Edit", "Inpainting Edit"):
        continue
    if cat.startswith("Select the"):
        continue
    # Skip already-seen titles (keep first/main occurrence)
    if cat in seen_titles:
        continue
    seen_titles.add(cat)
    add(f"DALL-E: {cat}", prompt_text, "DALL-E 2", "Business Graphics")

# ── Chapter 8: MidJourney — 10 Sample Prompts (lines 980-1009) ──
# Pattern: "N. Title\n\"prompt\"\nDescription"
mj_section = text.split("10 Sample MidJourney Prompts")[1] \
    if "10 Sample MidJourney Prompts" in text else ""
mj_section = mj_section.split("Conclusion")[0] \
    if "Conclusion" in mj_section else ""

# Parse: "N. Title\n\"prompt\" --ar ...\""
mj_pattern = re.findall(r'(\d+)\.\s*(.+?)\n\s*"([^"]+)"', mj_section, re.DOTALL)
for num, title, prompt_text in mj_pattern:
    add(f"MidJourney #{num}: {title.strip()}", prompt_text.strip(), "MidJourney", "Sample")

# ── Write output ──
with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    json.dump(prompts, f, indent=2, ensure_ascii=False)
print(f"Extracted {len(prompts)} prompts to {OUTPUT_FILE}")

if rejected:
    with open(REJECTED_FILE, "w", encoding="utf-8") as f:
        json.dump(rejected, f, indent=2, ensure_ascii=False)
    print(f"Rejected {len(rejected)} entries to {REJECTED_FILE}")
