# Skill: Prompt Ingestion & Cleaning

## Purpose

Ingest raw prompt files (text, PDF-extracted text, JSON, etc.) into the prompt library. Clean, normalize, categorize, and store prompts with proper metadata, wildcard extraction, and negative prompt separation.

## When to Use

- User provides a file containing image generation prompts
- User wants to add prompts to the library from any source (PromptHero, personal collection, scraped data, etc.)
- User wants to clean and normalize prompts before ingestion

## Workflow

### Phase 1: Analyze the Source File

1. Read the file and identify:
   - Prompt delimiters (empty lines, markdown headers, numbered lists, etc.)
   - Section/category markers (e.g., `### Midjourney Prompts`)
   - Negative prompt indicators (`Negative prompt:`, `negative prompts:`)
   - Model-specific syntax patterns (MJ params, LoRA refs, weighted syntax, etc.)

2. Run initial analysis to count prompts, detect style distribution, and identify special syntax:
   ```
   python3 analyze_prompts.py <input_file>
   ```

### Phase 2: Build/Update the Cleaning Script

Create or update `clean_<source>.py` with these components:

#### Regex Patterns to Detect & Strip

| Pattern | Regex | Action |
|---|---|---|
| MJ params | `--(?:ar\|chaos\|stylize\|style\|stylea\|v\|q\|niji\|raw\|quality\|personalize\|profile\|s)(?:\s+[\S]+)?` | Strip entirely |
| LoRA refs | `<lora:[^>]+>` | Replace with description if known, else strip |
| Weighted parens | `\(([^:)]+):\d+\.\d+\)` | Keep content, strip weight |
| Bracket weights | `\[([^:\]]+):\d+\.\d+\]` | Keep content, strip weight |
| Alt syntax | `\[([^\]\|]+)\|[^\]]+\]` | Keep first option |
| Attention | `::\d+` | Strip entirely |
| Double braces | `\{\{\s*([^}]+)\s*\}\}` | Unwrap to content |
| Multi-parens | `\({2,}([^)]+)\){2,}` | Unwrap to content |
| Trailing dash | `\s+-\s*$` | Strip |

#### LoRA Style Map

Maintain a dictionary mapping known LoRA names to descriptive style text:

```python
LORA_STYLE_MAP = {
    "niji3d": "anime 3D render style, cel-shaded anime aesthetic",
    "edg90hh": "urban streetwear style, edgy fashion",
    # Add new mappings as encountered
}
```

Unknown LoRAs: strip and flag. If the prompt has no other style descriptors after LoRA removal, **reject the prompt**.

#### Universal Negatives List

Maintain a set of negative prompt terms that are universally applicable (quality issues, anatomical errors, watermarks, etc.). These stay in the `negative_template`.

#### Style-Specific Negatives

Maint a dictionary of negative terms that are style-directive rather than quality-protective. These get extracted into the `style_negative` wildcard library:

```python
STYLE_SPECIFIC_NEGATIVES = {
    "realistic": "anti-realism for stylized/anime prompts",
    "photo": "anti-photo for painting/illustration prompts",
    "photorealistic": "anti-photorealism for stylized prompts",
    "3d": "anti-3d for 2D art prompts",
    "2d": "anti-2d for 3D art prompts",
    "painting": "anti-painting for photo prompts",
    "cartoons": "anti-cartoon for realistic prompts",
    "sketch": "anti-sketch for finished art prompts",
    "illustration": "anti-illustration for photo prompts",
    "anime": "anti-anime for realistic prompts",
    "monochrome": "anti-monochrome for color prompts",
    "grayscale": "anti-grayscale for color prompts",
}
```

**Key distinction:** Universal negatives remove bad things (deformed, watermark, blurry). Style-specific negatives steer the model away from a style (e.g., "photo" in a painting prompt's negative means "don't make it look like a photo" -- that's a style directive, not a quality fix).

### Phase 3: Run the Cleaning Script

```
python3 clean_<source>.py
```

This produces:
- `seeds/<source>_cleaned.json` -- cleaned prompts ready for ingestion
- `seeds/<source>_rejected.json` -- rejected prompts with reasons

### Phase 4: Review Results

Check:
1. **No remaining model-specific syntax** in cleaned prompts (search for `--`, `<lora:`, `::N`, etc.)
2. **Rejected prompts** -- verify rejection reasons are valid
3. **Style distribution** -- confirm prompts are categorized correctly
4. **Negative prompts** -- verify universal vs style-specific separation
5. **Wildcard library** -- check extracted wildcard categories
6. **Metadata** -- each prompt should have `original_source`, `original_prompt`, `date_added`, `source_file`, `source_index`

### Phase 5: Ingest into Database

```
PYTHONPATH=. python3 -m prompt_library import seeds/<source>_cleaned.json
```

Verify:
```
PYTHONPATH=. python3 -m prompt_library list-prompts
PYTHONPATH=. python3 -m prompt_library list-styles
PYTHONPATH=. python3 -m prompt_library list-wildcards
```

### Phase 6: Spot-Check Rendering

```
PYTHONPATH=. python3 -m prompt_library render <prompt_identifier> --style comma-separated --seed 42
```

## Style Detection Rules

After cleaning, assign style profiles based on prompt structure:

| Style | Detection Rule |
|---|---|
| `comma-separated` | Default for all prompts |
| `everyday-speech` | 2+ full sentences (20+ chars each) separated by `.!?` |
| `enhanced-prompt` | Original had weighted syntax `(tag:N.N)` or `[tag:N.N]` |
| `lisp-like` | Prompt is valid JSON structure |
| `structured-fields` | Prompt has labeled key-value sections (Subject:, Clothing:, Environment:, Camera:, Lighting:, Style Details:, etc.) |
| `booru-tags` | (future) Danbooru-style tag format with rating, character, artist tags |

## Rejection Criteria

Reject a prompt if:
- Less than 15 characters after cleaning
- Less than 3 words after cleaning
- No alphabetic content after cleaning
- Unknown LoRA removed with no style replacement (prompt likely degraded)

## Metadata Schema

Every prompt must include:

```json
{
  "original_source": "stable-diffusion|midjourney|flux|dall-e|etc",
  "original_prompt": "<full raw text including negatives>",
  "date_added": "ISO 8601 timestamp",
  "source_file": "filename.ext",
  "source_index": 0,
  "cleaning_issues": ["list of issues encountered"],
  "lora_replaced": [{"name": "...", "replaced_with": "..."}],
  "lora_removed": [{"name": "..."}],
  "mj_params_removed": true,
  "style_specific_negatives": [{"term": "...", "meaning": "..."}],
  "structured_json": true
}
```

## File Naming Conventions

- Cleaning script: `clean_<source>.py` (e.g., `clean_prompthero.py`)
- Cleaned output: `seeds/<source>_cleaned.json`
- Rejected output: `seeds/<source>_rejected.json`
- Analysis script: `analyze_<source>.py` (optional, for initial exploration)

## Updating the Pipeline

When encountering new syntax patterns:
1. Add regex to the cleaning script
2. Add to this skill doc
3. If new LoRA encountered, add to `LORA_STYLE_MAP` with descriptive replacement
4. If new style-specific negative found, add to `STYLE_SPECIFIC_NEGATIVES`
5. If new universal negative found, add to `UNIVERSAL_NEGATIVES`

## Structured-Fields Source Handling

For sources using the key-value field format (e.g., PromptDexter):

### Known Field Keys
```
Subject, Clothing, Action, Environment, Camera, Lighting, Objects, Style Details, Hair, Accessories
```

### Parsing Rules
- Concept line is the first line(s) before any field label
- Fields are `Label: value` pairs, case-insensitive match on known field names
- Continuation lines (no field label, after a field) append to the previous field
- Blank lines separate concept from fields but do NOT split the prompt

### Style Variations Generated
Each structured prompt produces 4 style variants:
1. **structured-fields** -- original key-value format as-is
2. **comma-separated** -- all field values joined with commas
3. **everyday-speech** -- fields woven into prose ("Subject wearing Clothing, Action in Environment")
4. **enhanced-prompt** -- Style Details and Subject get `(value:1.2)` / `(value:1.1)` weights, rest comma-joined

### Metadata
Structured prompts include additional metadata:
```json
{
  "structured_fields": {"Subject": "...", "Clothing": "...", ...},
  "field_keys_present": ["Subject", "Clothing", ...]
}
```
