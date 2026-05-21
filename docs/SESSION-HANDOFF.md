# Prompt Library - Session Handoff

## Project Overview

This is a prompt library for image generation prompts. It stores prompts across multiple writing styles, manages reusable wildcard vocabularies, and supports deterministic prompt rendering with seed-based wildcard selection.

**Repository:** `git@github.com:michaelbrave/Prompt-Library.git`
**Working directory:** `/var/home/mike/Desktop/Prompt-Library/Prompt-Library/`

## Current State (as of May 21, 2026)

### Database
- **Location:** `data/prompts.db` (SQLite, excluded from git)
- **429 prompts** ingested from 11 sources
- **18 wildcard categories** with 416 values (242 multi-word)
- **5 style profiles** active
- **482 wildcard bindings** across prompts (templates retrofitted with `{key}` syntax)

### Ingested Sources
| Source | File | Prompts | Wildcards Added |
|---|---|---|---|
| PromptHero | `seeds/prompthero_cleaned.json` | 80 (stable-diffusion: 38, midjourney: 30, flux: 5, nano-banana: 7) | `style_negative` (10 values) |
| PromptDexter | `seeds/promptdexter_cleaned.json` | 29 | none (uses structured fields) |
| MidJourney Book | `seeds/midjourney_book_cleaned.json` | 30 | expanded patterns: lighting, style_medium, mood, location, composition |
| Lexica | `seeds/lexica_cleaned.json` | 7 | expanded patterns for style_medium, lighting, mood, location, composition, clothing |
| Character Generator | `seeds/character_generator_cleaned.json` | 1 | 6 (gender, age, ethnicity, character_class, pose_setting, time_of_day) |
| CivitAI | `seeds/civitai_cleaned.json` | 86 | +104 wildcard values across all existing categories |
| BitBurner DreamLike | `seeds/bitburner_cleaned.json` | 99 | +45 wildcard bindings, minor wildcard value additions |
| BitBurner SD2 | `seeds/bitburner-sd2_cleaned.json` | 97 | +17 wildcard bindings |

### Rejected Prompts (kept for review)
- `seeds/prompthero_rejected.json` - 1 prompt (unknown LoRA with no replacement)
- `seeds/promptdexter_rejected.json` - 0 prompts
- `seeds/lexica_rejected.json` - 0 prompts
- `seeds/midjourney_book_rejected.json` - 0 prompts
- `seeds/civitai_rejected.json` - 1 prompt (no alphabetic content, all LoRA tags)
- `seeds/bitburner_rejected.json` - 0 prompts
- `seeds/bitburner-sd2_rejected.json` - 1 prompt ("space marine" - too short)

## Architecture

### Python Package: `prompt_library/`
```
prompt_library/
  __init__.py       - Package exports
  __main__.py       - CLI entry point
  cli.py            - argparse CLI (init, reset, import, diff, render, list-*, search, validate)
  db.py             - SQLite connection, initialize, reset
  importer.py       - JSON import, upsert logic, diff before import
  renderer.py       - Prompt rendering with wildcard selection and seed support
  wildcards.py      - Wildcard extraction from templates, replacement, validation
```

### Key Scripts (standalone, not in package)
| Script | Purpose |
|---|---|
| `clean_prompts.py` | Universal cleaner - auto-detects format (dream_factory, structured, sectioned, raw), strips MJ/LoRA/weight syntax, generates style variants |
| `extract_wildcards.py` | Scans all prompt text in DB, extracts recurring terms into categorized wildcard definitions (expanded patterns for Lexica) |
| `retrofit_wildcards.py` | Replaces literal wildcard values in templates with `{key}` syntax and creates bindings |
| `analyze_prompts.py` | Initial analysis of raw prompt files (style detection, syntax counting) |

### Schema: `schemas/sqlite.sql`
12 tables: `prompts`, `prompt_versions`, `prompt_style_profiles`, `prompt_templates`, `prompt_template_versions`, `wildcard_definitions`, `wildcard_values`, `prompt_wildcard_bindings`, `prompt_sets`, `prompt_set_members`, `imports`, `exports`

### Seed Files: `seeds/`
- `prompts.example.json` - Example import format (never ingested, just reference)
- `wildcards.example.json` - Example wildcard format (never ingested, just reference)
- `*_cleaned.json` - Ready-to-import cleaned data
- `*_rejected.json` - Rejected prompts with reasons

### Skill Docs: `docs/`
- `skill-prompt-ingestion.md` - General prompt ingestion workflow (6 phases)
- `skill-wildcard-extraction.md` - Wildcard extraction and categorization
- `skill-dream-factory-ingestion.md` - Dream Factory `.prompts` format parsing

## Style Families

| Style | Syntax Family | Description |
|---|---|---|
| `comma-separated` | `comma-separated` | Default keyword/tag lists |
| `everyday-speech` | `everyday-speech` | Natural language prose |
| `enhanced-prompt` | `enhanced-prompt` | Weighted syntax `(tag:1.2)` |
| `lisp-like` | `lisp-like` | JSON/S-expression structured |
| `structured-fields` | `structured-fields` | Key-value labeled sections (Subject:, Clothing:, etc.) |

Schema CHECK constraint on `syntax_family`:
```
('everyday-speech', 'comma-separated', 'booru-tags', 'enhanced-prompt', 'lisp-like', 'structured-fields', 'natural_language', 'pony-booru')
```

## Wildcard Categories in DB

| Category | Values | Examples |
|---|---|---|
| `action_pose` | 24 | gazing, standing, sitting, holding |
| `age` | 5 | old, young, middle aged, handsome, attractive |
| `camera_angle` | 26 | close-up, wide-angle, 85mm lens, bokeh |
| `character_class` | 11 | knight, ranger, paladin, barbarian, bard |
| `clothing` | 65 | denim jacket, white t-shirt, dress, veil |
| `color_palette` | 23 | warm orange, deep blue, golden yellow |
| `composition` | 12 | reflection, tight composition, symmetrical |
| `ethnicity` | 8 | irish, scottish, english, ukrainian |
| `gender` | 2 | woman, man |
| `hair` | 24 | dark hair, tousled hair, blonde hair |
| `lighting` | 34 | golden hour, rim light, soft shadows |
| `location_environment` | 50 | urban, beach, mountains, studio |
| `mood_atmosphere` | 30 | warm, vibrant, dramatic, dreamy |
| `person_subject` | 21 | young woman, young man, male model |
| `pose_setting` | 5 | sitting on the cliff, leaning against a tree |
| `style_medium` | 53 | photography, oil painting, photorealistic |
| `style_negative` | 10 | photo, painting, anime, 3d, 2d |
| `time_of_day` | 4 | a moonlit night, during the day, at sunrise |

## How to Run Things

### Initialize/Reset Database
```bash
PYTHONPATH=. python3 -m prompt_library init
PYTHONPATH=. python3 -m prompt_library reset --force
```

### Import Cleaned JSON
```bash
PYTHONPATH=. python3 -m prompt_library import seeds/<source>_cleaned.json
PYTHONPATH=. python3 -m prompt_library import seeds/<source>_cleaned.json --dry-run
PYTHONPATH=. python3 -m prompt_library diff seeds/<source>_cleaned.json
```

### List/Query
```bash
PYTHONPATH=. python3 -m prompt_library list-prompts
PYTHONPATH=. python3 -m prompt_library list-prompts --status active
PYTHONPATH=. python3 -m prompt_library list-styles
PYTHONPATH=. python3 -m prompt_library list-wildcards
PYTHONPATH=. python3 -m prompt_library search "portrait"
```

### Render Prompts
```bash
PYTHONPATH=. python3 -m prompt_library render <identifier> --style comma-separated --seed 42
PYTHONPATH=. python3 -m prompt_library render <identifier> --all-styles --seed 42
PYTHONPATH=. python3 -m prompt_library render <identifier> --style enhanced-prompt --overrides '{"gender": "woman"}'
```

### Validate
```bash
PYTHONPATH=. python3 -m prompt_library validate
```

### Extract Wildcards from Existing Prompts
```bash
python3 extract_wildcards.py
```

### Retrofit Templates with Wildcard Syntax
```bash
python3 retrofit_wildcards.py --dry-run   # Preview changes
python3 retrofit_wildcards.py             # Apply changes
```

### Clean New Source Files
```bash
python3 clean_prompts.py input.txt --source mysource           # Auto-detect format
python3 clean_prompts.py input.txt --source mysource --dry-run  # Preview
python3 clean_prompts.py input.txt --source mysource --format raw  # Force format
```

Supported auto-detected formats:
- `dream_factory` - Dream Factory `.prompts` format (`[config]`, `[prompts]`, `!SETTING=`)
- `structured` - Structured fields (`Subject:`, `Clothing:`, `Environment:`, etc.)
- `sectioned` - Section headers (`### Midjourney Prompts`)
- `raw` - Plain text, one prompt per blank-line-separated block

## Ingestion Workflow (for new files)

1. **Place raw file** in repo root (e.g., `new_source.txt`)
2. **Analyze** (optional): `python3 analyze_prompts.py new_source.txt`
3. **Clean**: `python3 clean_prompts.py new_source.txt --source mysource`
4. **Review**: Check `seeds/mysource_cleaned.json` and `seeds/mysource_rejected.json`
5. **Import**: `PYTHONPATH=. python3 -m prompt_library import seeds/mysource_cleaned.json`
6. **Verify**: `list-prompts`, `list-wildcards`, spot-check with `render`
7. **Extract wildcards** (if new source adds significant content): `python3 extract_wildcards.py`
8. **Retrofit** (if new wildcards found): `python3 retrofit_wildcards.py`
9. **Commit and push**

## Key Design Decisions

- **Negative prompt separation**: Universal negatives (deformed, watermark, bad anatomy) stay in `negative_template`. Style-specific negatives (photo in a painting prompt, anime in a realistic prompt) go into `style_negative` wildcard library.
- **LoRA handling**: Known LoRAs get replaced with descriptive style text. Unknown LoRAs are silently stripped (prompt preserved without them). Only prompts entirely composed of LoRA tags are rejected (no alphabetic content).
- **MJ params**: All `--ar`, `--stylize`, `--v`, etc. stripped entirely. Not stored anywhere.
- **Structured-fields prompts**: Each produces 4 style variants (structured-fields, comma-separated, everyday-speech, enhanced-prompt) by flattening the key-value fields differently.
- **Dream Factory format**: Each `[prompts]` block becomes a wildcard definition. Single-value connector blocks become inline template text. For standalone prompt collections (like BitBurner), the config/header must be pre-processed out and the file run as `raw` format instead.
- **CivitAI token stripping**: Score tags (`score_7`, `score_9`), artist tags (`@artistname`), `BREAK` keywords, and model markers (`ye-pop`) are stripped from prompts during cleaning. Stripping occurs after weight syntax resolution so `@[artist|...]` constructs are properly handled.
- **Wildcard weights**: `min(count / 5.0, 2.0)`. Minimum 2 occurrences to be extracted.
- **Metadata**: Every prompt stores `original_source`, `original_prompt`, `date_added`, `source_file`, `source_index` in the metadata JSON column.

## Known Issues / TODOs

1. **Retrofit quality**: Some retrofitted templates have semantic awkwardness (e.g., "young bride with glasses and trimmed beard") because specific original text was replaced with random wildcard values. Manual review/editing of specific templates may be needed.
2. **Booru-tags style**: Listed in schema but never used. CivitAI prompts use Danbooru-style tags (1girl, solo, score_N, @artist) in comma-separated format, not the dedicated `booru-tags` style profile.
3. **PostgreSQL**: Schema is SQLite-only. README recommends PostgreSQL for production but we haven't built the postgres.sql migration yet.
4. **Version history**: Tables exist but versioning is minimal (only creates version 1 on import).
5. **Prompt sets**: Tables exist but no sets created yet.
6. **No tests**: `tests/` directory exists but is empty.
7. **midjourney-book.txt**: Raw source file untracked in repo (needs pre-processing for preamble stripping before clean_prompts.py).
8. **CivitAI model markers**: `ye-pop` (and likely other model names) appear as standalone lines in CivitAI prompts. Current cleaner strips `ye-pop` but the pattern is hardcoded and may not cover all models.

## Next Likely Tasks

- Review retrofitted templates for semantic quality, fix awkward replacements
- Ingest more prompt files from user
- Add booru-tags style profile and convert Danbooru-style CivitAI prompts to use it
- Build PostgreSQL schema migration
- Add unit tests
- Handle PDF input (user mentioned PDFs as a possible source format)
- Make CivitAI model marker stripping configurable/pattern-based instead of hardcoded for `ye-pop`
- Clean up temp files (`bitburner-dreamlike_raw.txt`, `bitburner-dreamlike.prompts`)

## Git Info

- **Remote:** `git@github.com:michaelbrave/Prompt-Library.git` (SSH)
- **Branch:** `main`
- **Local config:** `user.name = michaelbrave`, `user.email = mike@brave.dev`
- **Last commit:** "Add prompt library infrastructure with SQLite schema, CLI, ingestion pipeline, and wildcard extraction"

## Environment Notes

- Python 3.13.13 at `/usr/bin/python3`
- No pip installed - use `PYTHONPATH=.` for running modules
- SQLite available via stdlib
- SSH auth to GitHub works (`ssh -T git@github.com` succeeds)
