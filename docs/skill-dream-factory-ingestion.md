# Skill: Dream Factory Prompt Ingestion

## Purpose

Parse and ingest Dream Factory format `.prompts` files into the prompt library. These files contain a single prompt template with multiple `[prompts]` blocks that serve as wildcard pools for randomized prompt generation.

## When to Use

- User provides a `.prompts` file in Dream Factory format
- User has prompt generator files from CivitAI, Reddit, or community sources
- The file uses `[config]` and `[prompts]` block structure

## Dream Factory Format Structure

```
# Header comments with metadata
[config]
!SETTING = value
!NEG_PROMPT = negative prompt text
!DELIM = " "

[prompts]
value1
value2
value3

[prompts]
, connector text

[prompts]
option_a
option_b
```

### Key Components

| Section | Purpose |
|---|---|
| `# comments` | Header metadata (author, model requirements, links) |
| `[config]` | Generation settings and negative prompt |
| `!NEG_PROMPT` | Negative prompt for the generator |
| `!DELIM` | Delimiter between wildcard values (usually `" "`) |
| `[prompts]` | Wildcard pool block - one value selected per block |

## Workflow

### Phase 1: Parse the File

Create `clean_<name>.py` with these parsing steps:

1. Extract header comments (author, model info, links)
2. Parse `[config]` block for settings and negative prompt
3. Parse each `[prompts]` block as a wildcard pool
4. Build template string with `{wildcard_key}` placeholders

### Phase 2: Classify Wildcard Blocks

Each `[prompts]` block is classified:

| Block Type | Detection | Handling |
|---|---|---|
| Single connector | 1 value starting with `,` | Inline text in template |
| Single literal | 1 value, not a connector | Inline text in template |
| Multi-option | 2+ values | Becomes a wildcard definition |

### Phase 3: Generate Meaningful Wildcard Keys

Map block content to semantic keys:

```python
key_map = {
    "woman": "gender",
    "man": "gender",
    "old": "age",
    "young": "age",
    "knight": "character_class",
    "sitting on the cliff": "pose_setting",
    "a moonlit night": "time_of_day",
    "irish": "ethnicity",
    # ... etc
}
```

Fallback: `option_{index:02d}` for unrecognized blocks.

### Phase 4: Clean Negative Prompt

Parse `!NEG_PROMPT`:
- Strip weighting syntax `(term:N.N)`
- Strip LoRA refs `<lora:name:weight>`
- Separate universal negatives (quality, anatomy) from style-specific negatives
- Store universal negatives in `negative_template`
- Store style-specific terms in `style_specific_negatives` metadata

### Phase 5: Build Output JSON

```json
{
  "wildcard_library": {
    "gender": ["woman", "man"],
    "age": ["old", "young", "middle aged", "handsome", "attractive"],
    "character_class": ["knight", "ranger", "paladin", ...]
  },
  "prompt_identifiers": [{
    "identifier": "fantasy_character_generator_001",
    "concept": "80s-90s fantasy art character generator",
    "status": "active",
    "metadata": {
      "original_source": "dream_factory",
      "dream_factory_settings": {...},
      "header_info": {...}
    },
    "wildcard_refs": ["gender", "age", "character_class", ...],
    "style_variations": [...]
  }]
}
```

### Phase 6: Ingest

```
PYTHONPATH=. python3 -m prompt_library import seeds/<name>_cleaned.json
```

## Template Construction Rules

1. Single-value blocks that are connectors (`,`, `descent,`) → inline text
2. Single-value blocks that are literals (`close up of 1`) → cleaned inline text
3. Multi-value blocks → `{wildcard_key}` placeholder
4. Join all parts with spaces, then normalize:
   - Collapse multiple spaces
   - Fix comma spacing (` ,` → `,`, `,  ` → `, `)
   - Capitalize first letter

## Metadata to Preserve

- `dream_factory_settings` - all `!SETTING = value` pairs
- `header_info` - parsed header comments (author, model requirements, links)
- `original_source` - `"dream_factory"`
- `source_file` - original filename
- `style_specific_negatives` - style-directive terms from negative prompt

## Files

- `clean_character_generator.py` - example cleaning script for Dream Factory format
- `docs/skill-prompt-ingestion.md` - general ingestion skill
- `docs/skill-wildcard-extraction.md` - wildcard extraction skill
