# Style Variation Generation Plan

The library should eventually have a complete set of prompt templates for every stable prompt across the standard style profiles:

- `everyday-speech`
- `comma-separated`
- `booru-tags`
- `enhanced-prompt`
- `lisp-like`
- `structured-fields`

The current database already has mixed coverage. This plan uses a resumable job runner to find missing style variants, send each rewrite task to an external LLM, validate the response, insert the new template, and mark the job complete.

## Recommended Rollout

Do not start with all 700k prompts.

1. Start with curated evaluation sets, especially `eval-core-100`.
2. Review a sample of generated variants for each style family.
3. Tune the instructions/examples if a style is drifting.
4. Fill the four specialized eval sets.
5. Only then expand to broader prompt pools.

This keeps LLM spend focused on prompts that are already selected for benchmark use. Full-library generation can happen later, after the target style rules are stable.

## Tool

Use:

```bash
python tools/generate_missing_styles.py --prompt-set eval-core-100 --limit 25 --llm-cmd "YOUR_LLM_WORKER_COMMAND"
```

The script:

- ensures the standard style profiles exist
- creates/uses `style_generation_jobs`
- finds enabled prompts missing one or more target styles
- selects the best existing source template for each prompt
- builds a JSON task with instructions and an example
- sends that task to the configured LLM command on stdin
- expects one JSON object on stdout
- validates wildcard preservation
- upserts `prompt_templates`
- writes `prompt_template_versions`
- marks the job `completed` or `failed`

## Useful Commands

Preview missing work without writing jobs:

```bash
python tools/generate_missing_styles.py --prompt-set eval-core-100 --limit 20 --dry-run
```

Generate only one style:

```bash
python tools/generate_missing_styles.py --prompt-set eval-core-100 --style booru-tags --limit 20 --llm-cmd "YOUR_LLM_WORKER_COMMAND"
```

Export task JSON files for manual or offline workers:

```bash
python tools/generate_missing_styles.py --prompt-set eval-core-100 --limit 20 --task-dir work/style-tasks
```

Retry failed jobs:

```bash
python tools/generate_missing_styles.py --prompt-set eval-core-100 --limit 20 --retry-failed --llm-cmd "YOUR_LLM_WORKER_COMMAND"
```

Process active prompts outside a prompt set:

```bash
python tools/generate_missing_styles.py --limit 100 --llm-cmd "YOUR_LLM_WORKER_COMMAND"
```

## LLM Worker Contract

The LLM command receives one JSON object on stdin. It must write exactly one JSON object to stdout and no markdown.

Required output:

```json
{
  "positive_template": "rewritten prompt template",
  "negative_template": "negative prompt template or empty string",
  "notes": "brief explanation of rewrite choices"
}
```

Rules for workers:

- Preserve the original scene intent.
- Rewrite only the prompt style, not the concept.
- Preserve every wildcard listed in `required_wildcards`.
- Do not invent new wildcard placeholders.
- Keep wildcard placeholders exactly as `{wildcard_key}`.
- Return valid JSON only.
- Do not wrap JSON in markdown fences.

## Example Worker Input

```json
{
  "task": "rewrite_prompt_style_variant",
  "prompt_identifier": "example_prompt",
  "concept": "cinematic portrait of a traveler in a neon market",
  "target_style": {
    "identifier": "booru-tags",
    "syntax_family": "booru-tags",
    "negative_prompt_strategy": "standard",
    "description": "Danbooru-style tags with underscores, short tags, and comma separation."
  },
  "source_style": "comma-separated",
  "source_positive_template": "{person_subject}, neon market, {lighting}, {camera_angle}, cinematic, detailed",
  "source_negative_template": "blurry, low quality",
  "required_wildcards": ["camera_angle", "lighting", "person_subject"],
  "example": {
    "positive_template": "{person_subject}, {location_environment}, {lighting}, {camera_angle}, {mood_atmosphere}, {style_medium}, detailed_background",
    "negative_template": "lowres, blurry, bad_anatomy, watermark"
  }
}
```

Valid worker output:

```json
{
  "positive_template": "{person_subject}, neon_market, {lighting}, {camera_angle}, cinematic_lighting, detailed_background",
  "negative_template": "lowres, blurry, bad_anatomy, watermark",
  "notes": "Converted prose fragments into booru-style comma tags while preserving required wildcards."
}
```

## Validation

The runner rejects responses when:

- JSON is invalid
- required keys are missing
- output values are not strings
- a new wildcard placeholder appears
- a required wildcard is missing from the positive template

Use `--allow-wildcard-drop` only for a deliberate cleanup pass where a style should omit some source placeholders.

## Database State

The runner writes to:

- `prompt_style_profiles`
- `prompt_templates`
- `prompt_template_versions`
- `style_generation_jobs`

`style_generation_jobs.status` can be:

- `pending`
- `running`
- `completed`
- `failed`
- `skipped`

Failed jobs keep `error_log` for later inspection. Completed jobs keep the original task and response payloads for auditability.

## Review Policy

After each batch:

1. Render a sample of completed prompts across all styles.
2. Check that wildcards still bind correctly.
3. Check that booru and lisp-like styles are structurally distinct from comma-separated prompts.
4. Check that negative prompts are not bloated or contradictory.
5. Tune the style examples before continuing if quality drifts.

Recommended verification:

```bash
python -m prompt_library.cli validate
python -m prompt_library.cli render PROMPT_IDENTIFIER --all-styles --seed 123
```

## Better Long-Term Shape

For the evaluation layer, fill all styles after the selected prompt pool is reviewed and narrowed. For the full library, generate style variants in priority order rather than trying to complete everything in one pass:

1. eval sets
2. highly rated or manually curated prompt sets
3. prompts with strong wildcard coverage
4. remaining active prompts

That keeps compute focused on prompts likely to be used and avoids spending model calls on noisy imports that may later be archived.
