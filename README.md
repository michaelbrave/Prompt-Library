# prompt-library

A SQLite-backed library of reusable image-generation prompts, style variants,
wildcard vocabularies, and import tooling.

The repository intentionally tracks `data/prompts.db`. Treat that file as the
current portable snapshot of the prompt library.

## Repository Layout

```text
data/prompts.db          Current SQLite prompt database snapshot
schemas/sqlite.sql       Database schema
prompt_library/          CLI, importer, renderer, database helpers
clean_prompts.py         Universal prompt-source cleaner
tools/                   Source-specific converters and analysis helpers
seeds/                   Cleaned JSON import files and examples
docs/                    Ingestion notes and handoff docs
```

## Quick Start

List prompt records:

```bash
python -m prompt_library.cli list-prompts
```

Search prompts:

```bash
python -m prompt_library.cli search "portrait"
```

Render one prompt:

```bash
python -m prompt_library.cli render PROMPT_IDENTIFIER --all-styles --seed 123
```

Validate wildcard bindings:

```bash
python -m prompt_library.cli validate
```

## Database Workflow

Initialize an empty database:

```bash
python -m prompt_library.cli init
```

Reset the database from the schema:

```bash
python -m prompt_library.cli reset --force
```

Import a cleaned seed file:

```bash
python -m prompt_library.cli import seeds/example_cleaned.json
```

Preview an import without writing:

```bash
python -m prompt_library.cli import seeds/example_cleaned.json --dry-run
python -m prompt_library.cli diff seeds/example_cleaned.json
```

The default database path is `data/prompts.db`. You can target another SQLite
file with `--db path/to/file.db`.

## Cleaning Sources

Use the universal cleaner for raw prompt sources:

```bash
python clean_prompts.py raw_source.txt --source source_name
```

It auto-detects these formats:

- `dream_factory`: Dream Factory `.prompts` files with `[config]` and `[prompts]`.
- `structured`: field-based prompts such as `Subject:`, `Lighting:`, and `Camera:`.
- `sectioned`: files with `###` section headers.
- `raw`: blank-line-separated prompt blocks.

Override detection when needed:

```bash
python clean_prompts.py raw_source.txt --source source_name --format sectioned
```

The cleaner writes:

- `seeds/<source>_cleaned.json`
- `seeds/<source>_rejected.json`

Then import the cleaned file into SQLite:

```bash
python -m prompt_library.cli import seeds/source_name_cleaned.json
```

## Preparing Inbox Files

Raw prompt books and OCR exports belong in `inbox/`, which is ignored by Git.
Prepare the top-level `.txt` files into chunked seed files:

```bash
python tools/prepare_inbox.py
```

This writes `seeds/inbox/*_cleaned.json` files with up to 500 prompts each and
stable source-prefixed identifiers. Preview first with:

```bash
python tools/prepare_inbox.py --dry-run
```

Import prepared chunks:

```bash
for file in seeds/inbox/*_cleaned.json; do
  python -m prompt_library.cli import "$file"
done
```

Large zipped `.prompts` packs can be imported without creating intermediate
JSON files:

```bash
python tools/import_prompt_zip.py inbox/kkwprompt.zip
```

`data/prompts.db` is tracked with Git LFS because full prompt-pack imports can
push the SQLite database beyond GitHub's normal file-size limit.

## JSON Import Shape

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
      "status": "active",
      "metadata": {},
      "wildcard_refs": ["subject", "lighting"],
      "style_variations": [
        {
          "identifier": "comma-separated",
          "syntax_family": "comma-separated",
          "positive_template": "{subject}, neon alley, {lighting}, highly detailed",
          "negative_template": "blurry, low quality",
          "negative_prompt_strategy": "standard"
        }
      ]
    }
  ]
}
```

## Git Notes

`data/prompts.db` is tracked on purpose. SQLite sidecar files and local backups
remain ignored:

- `*.db-wal`
- `*.db-shm`
- `*.db-journal`
- `*.db.bak`

The database helper uses SQLite's default rollback journal mode so committed
writes live in `data/prompts.db` instead of ignored sidecar files.
