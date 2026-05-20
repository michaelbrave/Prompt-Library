# prompt-library

Spec sheet for a dedicated prompt-library repository used by `image-workflow`.

## Purpose

The prompt library is the source of truth for reusable image-generation prompts, prompt style variants, wildcard vocabularies, and prompt metadata used during model comparison, merge screening, scorer training, and later data-pipeline work.

It must preserve equivalent prompt intent across different models while allowing each model family to use the prompt syntax that performs best for it.

## Design Goals

- Store more than 10,000 prompt entries without turning search, review, or imports into a bottleneck.
- Keep prompt intent stable through a durable prompt identifier.
- Support multiple prompt-writing styles for the same intent.
- Support reusable wildcard libraries and per-prompt wildcard bindings.
- Track enough metadata to reproduce generated images and scorer-training exports.
- Allow human review and automated scoring systems to reference prompts without copying prompt text everywhere.
- Make local development easy while keeping the production storage path scalable.

## Storage Recommendation

Use PostgreSQL as the primary database for the prompt library.

SQLite is fine for local cache files, one-user prototypes, test fixtures, and import/export snapshots. It can hold 10,000 rows comfortably, but the prompt library is likely to need concurrent writes, richer search, metadata filtering, version history, and integration with review/scoring services. PostgreSQL is the better default once this becomes shared infrastructure.

Recommended split:

- PostgreSQL: canonical prompt library, version history, search indexes, review state, imports, and service API.
- SQLite: local read-only snapshot, unit tests, CLI smoke tests, and portable exports from PostgreSQL.
- JSON: human-editable seed/import format, matching the current `config/prompts.example.json` shape.

## Repository Shape

```text
prompt-library/
  README.md
  schemas/
    postgres.sql
  seeds/
    prompts.example.json
    wildcards.example.json
  migrations/
  docs/
    taxonomy.md
    import-export.md
  tests/
```

This README is the initial spec. The folders above are the intended next structure, not a requirement that all files exist immediately.

## Core Concepts

### Prompt Identifier

A stable ID for an intended image concept.

Required fields:

- `identifier`: unique, human-readable slug such as `character_portrait_001`.
- `concept`: plain-language intent shared across all style variants.
- `status`: `draft`, `active`, `deprecated`, or `archived`.
- `metadata`: JSON object for domain, composition, subject type, rating notes, or experiment labels.

### Prompt Style Profile

A reusable description of prompt syntax.

Examples:

- `everyday-speech`
- `comma-separated`
- `booru-tags`
- `lisp-structured`
- `pony-booru`

Required fields:

- `identifier`
- `syntax_family`
- `negative_prompt_strategy`
- `ordering_notes`
- `metadata`

### Prompt Template

A model-facing positive/negative prompt pair for one prompt identifier and one style profile.

Required fields:

- `prompt_identifier`
- `style_profile_identifier`
- `positive_template`
- `negative_template`
- `enabled`
- `notes`

The template can reference `{concept}` and bound wildcard keys such as `{subject}`, `{lighting}`, or `{camera}`.

### Wildcard Definition

A reusable vocabulary list.

Required fields:

- `wildcard_key`
- `values`
- `status`
- `notes`
- `metadata`

Wildcard values should be curated as data, not hidden inside individual prompt strings, so equivalent prompts can be expanded reproducibly.

### Prompt Wildcard Binding

Connects a prompt identifier to one or more wildcard definitions.

Required fields:

- `prompt_identifier`
- `wildcard_key`
- `required`
- `default_strategy`
- `notes`

### Prompt Version

Every meaningful edit to prompt concept, template text, wildcard bindings, or metadata should create a versioned record.

Version history must answer:

- what changed
- who or what changed it
- when it changed
- why it changed
- which generated images used the previous version

## Minimal PostgreSQL Tables

Initial canonical tables:

- `prompts`
- `prompt_versions`
- `prompt_style_profiles`
- `prompt_templates`
- `prompt_template_versions`
- `wildcard_definitions`
- `wildcard_values`
- `prompt_wildcard_bindings`
- `prompt_sets`
- `prompt_set_members`
- `imports`
- `exports`

Recommended generated-image integration tables, if kept in this repository:

- `rendered_prompts`
- `generation_references`
- `automated_prompt_scores`
- `human_prompt_reviews`

If image generation remains owned by `image-workflow`, keep those integration tables there and reference prompt-library IDs plus version IDs.

## Indexing

Minimum indexes:

- unique index on `prompts.identifier`
- unique index on `prompt_style_profiles.identifier`
- unique index on `prompt_templates(prompt_id, style_profile_id)`
- index on `prompt_templates.enabled`
- index on `prompt_wildcard_bindings(prompt_id)`
- index on `wildcard_values(wildcard_definition_id)`
- GIN index on prompt/template metadata JSONB
- full-text search index over `concept`, `positive_template`, `negative_template`, `notes`, and wildcard values

PostgreSQL extensions to consider:

- `pg_trgm` for fuzzy search and duplicate detection.
- `unaccent` if prompt text includes multilingual tags later.
- `vector` only if semantic prompt search becomes a real requirement.

## Import Format

The repository should continue accepting the current JSON shape:

```json
{
  "wildcard_library": {
    "subject": ["cyberpunk courier", "street mage"],
    "lighting": ["neon rim light", "soft rain reflections"]
  },
  "prompt_identifiers": [
    {
      "identifier": "character_portrait_001",
      "concept": "cinematic character portrait in a neon alley",
      "wildcard_refs": ["subject", "lighting"],
      "style_variations": [
        {
          "identifier": "everyday-speech",
          "syntax_family": "natural_language",
          "positive_template": "A {subject} in a neon alley, {lighting}, highly detailed.",
          "negative_template": "blurry, low quality",
          "negative_prompt_strategy": "minimal"
        }
      ]
    }
  ]
}
```

Import behavior:

- Upsert prompts by `identifier`.
- Upsert wildcard definitions by `wildcard_key`.
- Upsert style profiles by `identifier`.
- Upsert templates by `(prompt_identifier, style_profile_identifier)`.
- Create new version rows when canonical fields change.
- Reject templates that reference unbound wildcard keys.
- Keep imports idempotent.

## Rendering Rules

Rendering a prompt must produce:

- `prompt_identifier`
- `prompt_version_id`
- `style_profile_identifier`
- `template_version_id`
- selected wildcard values
- positive prompt
- negative prompt
- render seed

Wildcard selection must be deterministic when a seed is supplied.

## Prompt Sets

Prompt sets define stable evaluation groups.

Examples:

- `calibration-smoke-4`
- `sd15-comparison-baseline`
- `merge-screening-full`
- `scorer-training-anime-portrait`
- `human-review-disagreement-queue`

Prompt sets should support ordered membership, enabled/disabled state, tags, and version pinning.

## Calibration Workflow

The prompt library must support the existing workflow:

1. Select four calibration prompt identifiers.
2. Render each prompt across multiple style profiles.
3. Generate outputs per source model.
4. Score outputs with current third-party scorers.
5. Record best prompt style per model or model family.
6. Use the winning style profile for broader prompt sweeps.

## API Surface

Initial service or CLI operations:

- `import-json`
- `export-json`
- `list-prompts`
- `list-styles`
- `list-wildcards`
- `render-prompt`
- `create-prompt-set`
- `add-prompt-to-set`
- `search-prompts`
- `validate-templates`
- `diff-import`

## Validation Rules

- Prompt identifiers must be unique and stable.
- Template placeholders must resolve to `{concept}` or a bound wildcard key.
- Enabled templates require non-empty positive prompts.
- Negative prompts may be empty but must still be explicit.
- Wildcard definitions must not contain empty value lists.
- Prompt sets must not silently change historical meaning; use version pinning for reproducible experiments.

## PostgreSQL vs SQLite Decision

For 10,000 prompt entries alone, SQLite is technically enough. The reason to choose PostgreSQL is not row count; it is the operational shape around those rows.

Choose PostgreSQL because this library is expected to grow into:

- shared writes from CLI, UI, and import jobs
- full-text and fuzzy search
- JSONB metadata filtering
- durable version history
- concurrent review/scoring updates
- stable APIs for the generation pipeline
- future semantic search or embedding-backed retrieval

Keep SQLite support only as an adapter for tests and local snapshots, not as the canonical store.

## Open Questions

- Should generated-image provenance live in this repository or stay in `image-workflow`?
- Should prompt-library expose a service API immediately, or begin as migrations plus CLI?
- Should prompt versions be immutable rows from day one, or added after the first import/export pass?
- Which prompt taxonomies need first-class columns instead of JSONB metadata?
