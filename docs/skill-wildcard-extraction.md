# Skill: Wildcard Extraction & Categorization

## Purpose

Scan existing prompts in the library to extract recurring terms, categorize them into wildcard definitions, and store them in the database for reusable prompt composition.

## When to Use

- After ingesting a new batch of prompts
- When building out the wildcard vocabulary for prompt generation
- When reviewing prompt patterns to identify common elements
- Before rendering prompts that need wildcard value selection

## Workflow

### Phase 1: Run the Extraction Script

```
python3 extract_wildcards.py
```

This scans all prompt text sources in the database:
- `positive_template` from all enabled `prompt_templates`
- `negative_template` from all templates with content
- `original_prompt` from prompt metadata JSON
- Individual `structured_fields` values from structured-field prompts

### Phase 2: Review Extracted Categories

The script outputs a summary of each category with term counts and top examples. Check:
1. **Category accuracy** -- terms belong in the right category
2. **Duplicate terms** -- same concept appearing in multiple categories
3. **Noise** -- generic words that shouldn't be wildcards
4. **Missing categories** -- recurring patterns not captured

### Phase 3: Manual Curation (if needed)

After extraction, review and clean up:
- Remove overly generic terms (e.g., "the", "a", "with")
- Merge near-duplicates (e.g., "close-up" vs "close up")
- Split categories that are too broad
- Add missing categories for recurring patterns

### Phase 4: Verify Database

```
PYTHONPATH=. python3 -m prompt_library list-wildcards
```

## Wildcard Categories

### Current Categories

| Category | Description | Example Terms |
|---|---|---|
| `action_pose` | Subject actions and poses | gazing, standing, sitting, holding, leaning, walking |
| `camera_angle` | Camera framing and lens specs | close-up, wide-angle, 85mm lens, bokeh, shallow depth of field |
| `clothing` | Garments and wearable items | denim jacket, white t-shirt, dress, veil, sunglasses, hat |
| `color_palette` | Color schemes and tones | warm orange, deep blue, golden yellow, terracotta, pastel |
| `composition` | Image layout and arrangement | symmetrical composition, reflection, tight framing, blurred background |
| `hair` | Hair styles and descriptions | dark hair, tousled hair, blonde hair, tied back, messy bun |
| `lighting` | Light direction, quality, and effects | golden hour, rim light, soft shadows, cinematic lighting, high contrast |
| `location_environment` | Settings and backgrounds | urban, beach, mountains, studio, subway car, garden |
| `mood_atmosphere` | Emotional tone and ambiance | dreamy, moody, dramatic, vibrant, serene, mysterious |
| `person_subject` | Subject types and descriptions | young woman, young man, male model, female model, bride |
| `style_medium` | Art styles and rendering techniques | oil painting, photography, photorealistic, black and white, anime-inspired |
| `style_negative` | Style-directive negative terms | photo, painting, anime, 3d, 2d, sketch, monochrome |

### Adding New Categories

To add a new wildcard category:

1. Define the category name (snake_case, descriptive)
2. Add regex patterns to `CATEGORY_PATTERNS` in `extract_wildcards.py`:
   ```python
   CATEGORY_PATTERNS = {
       "new_category": [
           r'\b(term1|term2|term3)\b',
           r'\b(multi\s+word\s+term)\b',
       ],
       ...
   }
   ```
3. Run the extraction script
4. Verify terms are inserted correctly

### Pattern Guidelines

- Use `\b` word boundaries to avoid partial matches
- Use `?` for optional characters (e.g., `close-?up` matches both "close-up" and "closeup")
- Use `\s+` for flexible whitespace (e.g., `golden\s+hour`)
- Group alternatives with `|` inside parentheses
- Keep patterns case-insensitive by matching against lowercase text
- Test patterns against sample prompts before adding

## Weight Calculation

Wildcard values are assigned weights based on frequency:

```python
weight = min(count / 5.0, 2.0)
```

- Found 5+ times: weight 2.0 (maximum)
- Found 3-4 times: weight 0.6-0.8
- Found 2 times: weight 0.4
- Minimum threshold: 2 occurrences (terms found only once are excluded)

## Minimum Frequency Threshold

Terms must appear in **at least 2 prompts** to be extracted. This filters out one-off descriptions and captures genuinely recurring vocabulary.

## Database Schema

Wildcards are stored in two tables:

```sql
wildcard_definitions (id, wildcard_key, status, notes, metadata)
wildcard_values (id, wildcard_definition_id, value, weight, notes)
```

Each category becomes one `wildcard_definitions` row, with individual terms as `wildcard_values` rows.

## Binding Wildcards to Prompts

After extraction, wildcards can be bound to specific prompts via `prompt_wildcard_bindings`. This is done during prompt ingestion when the source data declares `wildcard_refs`, or manually via:

```sql
INSERT INTO prompt_wildcard_bindings (prompt_id, wildcard_definition_id, required, default_strategy)
VALUES (?, ?, 0, 'random');
```

## Updating the Extraction

When new prompts are ingested:
1. Run `extract_wildcards.py` again
2. New terms meeting the frequency threshold are added
3. Existing terms have their weights updated based on new counts
4. Use `INSERT OR IGNORE` to avoid duplicates

## Files

- `extract_wildcards.py` -- main extraction script
- `prompt_library/wildcards.py` -- wildcard utility functions
- `docs/skill-prompt-ingestion.md` -- related ingestion skill
