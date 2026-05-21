import json
import datetime
from .db import get_connection
from .wildcards import normalize_wildcard_key


def import_json_file(file_path, db_path=None, dry_run=False):
    conn = get_connection(db_path)
    cursor = conn.cursor()

    with open(file_path, 'r') as f:
        data = json.load(f)

    import_record = {
        'source_file': file_path,
        'status': 'processing',
        'rows_imported': 0,
        'rows_skipped': 0,
        'error_log': None,
        'created_at': datetime.datetime.now().isoformat()
    }

    try:
        if not dry_run:
            cursor.execute(
                "INSERT INTO imports (source_file, status, rows_imported, rows_skipped, created_at) VALUES (?, ?, ?, ?, ?)",
                (import_record['source_file'], import_record['status'], import_record['rows_imported'], import_record['rows_skipped'], import_record['created_at'])
            )
            import_id = cursor.lastrowid
        else:
            import_id = None

        wildcard_library = data.get('wildcard_library', {})
        imported_wildcards = upsert_wildcard_library(cursor, wildcard_library, dry_run)

        prompt_identifiers = data.get('prompt_identifiers', [])
        imported_prompts = upsert_prompts(cursor, prompt_identifiers, imported_wildcards, dry_run)

        if not dry_run:
            cursor.execute(
                "UPDATE imports SET status = 'completed', rows_imported = ?, completed_at = ? WHERE id = ?",
                (len(imported_prompts), datetime.datetime.now().isoformat(), import_id)
            )
            conn.commit()

        return {
            'status': 'success',
            'wildcards_imported': len(imported_wildcards),
            'prompts_imported': len(imported_prompts),
            'import_id': import_id
        }

    except Exception as e:
        if not dry_run:
            cursor.execute(
                "UPDATE imports SET status = 'failed', error_log = ? WHERE id = ?",
                (str(e), import_id)
            )
            conn.commit()
        raise


def upsert_wildcard_library(cursor, library, dry_run=False):
    imported = {}
    for key, values in library.items():
        normalized_key = normalize_wildcard_key(key)

        if not dry_run:
            cursor.execute(
                "INSERT OR IGNORE INTO wildcard_definitions (wildcard_key, status, created_at, updated_at) VALUES (?, 'active', datetime('now'), datetime('now'))",
                (normalized_key,)
            )
            cursor.execute("SELECT id FROM wildcard_definitions WHERE wildcard_key = ?", (normalized_key,))
            def_row = cursor.fetchone()
            def_id = def_row['id'] if def_row else None
        else:
            def_id = f"mock_{normalized_key}"

        if isinstance(values, list):
            for i, val in enumerate(values):
                if isinstance(val, str):
                    value_str = val
                    weight = 1.0
                elif isinstance(val, dict):
                    value_str = val.get('value', '')
                    weight = val.get('weight', 1.0)
                else:
                    continue

                if value_str and not dry_run:
                    cursor.execute(
                        "INSERT OR IGNORE INTO wildcard_values (wildcard_definition_id, value, weight, created_at) VALUES (?, ?, ?, datetime('now'))",
                        (def_id, value_str, weight)
                    )

        imported[normalized_key] = def_id

    return imported


def upsert_prompts(cursor, prompt_list, wildcard_map, dry_run=False):
    imported = []

    for prompt_data in prompt_list:
        identifier = prompt_data['identifier']
        concept = prompt_data['concept']
        status = prompt_data.get('status', 'draft')
        metadata = json.dumps(prompt_data.get('metadata', {}))
        wildcard_refs = prompt_data.get('wildcard_refs', [])

        if not dry_run:
            cursor.execute("SELECT id, concept, status, metadata FROM prompts WHERE identifier = ?", (identifier,))
            prompt_row = cursor.fetchone()
            if prompt_row:
                prompt_id = prompt_row['id']
                prompt_changed = (
                    prompt_row['concept'] != concept
                    or prompt_row['status'] != status
                    or (prompt_row['metadata'] or '{}') != metadata
                )
                if prompt_changed:
                    cursor.execute(
                        "UPDATE prompts SET concept = ?, status = ?, metadata = ?, updated_at = datetime('now') WHERE id = ?",
                        (concept, status, metadata, prompt_id),
                    )
                    cursor.execute("SELECT COALESCE(MAX(version), 0) + 1 FROM prompt_versions WHERE prompt_id = ?", (prompt_id,))
                    version = cursor.fetchone()[0]
                    cursor.execute(
                        "INSERT INTO prompt_versions (prompt_id, version, change_type, changed_by, change_reason, created_at) VALUES (?, ?, 'updated', 'import', ?, datetime('now'))",
                        (prompt_id, version, "Updated from import"),
                    )
            else:
                cursor.execute(
                    "INSERT INTO prompts (identifier, concept, status, metadata, created_at, updated_at) VALUES (?, ?, ?, ?, datetime('now'), datetime('now'))",
                    (identifier, concept, status, metadata)
                )
                prompt_id = cursor.lastrowid
                cursor.execute(
                    "INSERT INTO prompt_versions (prompt_id, version, change_type, changed_by, change_reason, created_at) VALUES (?, 1, 'created', 'import', ?, datetime('now'))",
                    (prompt_id, "Imported from source")
                )
        else:
            prompt_id = f"mock_{identifier}"

        style_variations = prompt_data.get('style_variations', [])
        for style_var in style_variations:
            style_identifier = style_var.get('identifier', style_var.get('syntax_family', 'unknown'))
            syntax_family = style_var.get('syntax_family', style_identifier)
            negative_prompt_strategy = style_var.get('negative_prompt_strategy', 'minimal')

            if not dry_run:
                cursor.execute(
                    "INSERT OR IGNORE INTO prompt_style_profiles (identifier, syntax_family, negative_prompt_strategy, created_at) VALUES (?, ?, ?, datetime('now'))",
                    (style_identifier, syntax_family, negative_prompt_strategy)
                )
                cursor.execute("SELECT id FROM prompt_style_profiles WHERE identifier = ?", (style_identifier,))
                style_row = cursor.fetchone()
                style_id = style_row['id'] if style_row else None

                positive = style_var.get('positive_template', '')
                negative = style_var.get('negative_template', '')
                notes = style_var.get('notes')

                cursor.execute(
                    "SELECT id, positive_template, negative_template, notes FROM prompt_templates WHERE prompt_id = ? AND style_profile_id = ?",
                    (prompt_id, style_id)
                )
                template_row = cursor.fetchone()
                if template_row:
                    template_id = template_row['id']
                    template_changed = (
                        template_row['positive_template'] != positive
                        or (template_row['negative_template'] or '') != negative
                        or template_row['notes'] != notes
                    )
                    if template_changed:
                        cursor.execute(
                            "UPDATE prompt_templates SET positive_template = ?, negative_template = ?, notes = ?, enabled = 1, updated_at = datetime('now') WHERE id = ?",
                            (positive, negative, notes, template_id)
                        )
                        cursor.execute("SELECT COALESCE(MAX(version), 0) + 1 FROM prompt_template_versions WHERE template_id = ?", (template_id,))
                        version = cursor.fetchone()[0]
                        cursor.execute(
                            "INSERT INTO prompt_template_versions (template_id, version, positive_template, negative_template, change_type, changed_by, created_at) VALUES (?, ?, ?, ?, 'updated', 'import', datetime('now'))",
                            (template_id, version, positive, negative)
                        )
                else:
                    cursor.execute(
                        "INSERT INTO prompt_templates (prompt_id, style_profile_id, positive_template, negative_template, enabled, notes, created_at, updated_at) VALUES (?, ?, ?, ?, 1, ?, datetime('now'), datetime('now'))",
                        (prompt_id, style_id, positive, negative, notes)
                    )
                    template_id = cursor.lastrowid
                    cursor.execute(
                        "INSERT INTO prompt_template_versions (template_id, version, positive_template, negative_template, change_type, changed_by, created_at) VALUES (?, 1, ?, ?, 'created', 'import', datetime('now'))",
                        (template_id, positive, negative)
                    )
            else:
                style_id = f"mock_{style_identifier}"
                template_id = f"mock_{style_identifier}_template"

        for ref in wildcard_refs:
            normalized_ref = normalize_wildcard_key(ref)
            if normalized_ref in wildcard_map:
                def_id = wildcard_map[normalized_ref]
                if not dry_run:
                    cursor.execute(
                        "INSERT OR IGNORE INTO prompt_wildcard_bindings (prompt_id, wildcard_definition_id, required, default_strategy) VALUES (?, ?, 0, 'random')",
                        (prompt_id, def_id)
                    )

        imported.append(identifier)

    return imported


def diff_import(file_path, db_path=None):
    conn = get_connection(db_path)
    cursor = conn.cursor()

    with open(file_path, 'r') as f:
        data = json.load(f)

    changes = {'new_prompts': [], 'updated_prompts': [], 'new_wildcards': [], 'existing_wildcards': []}

    for prompt_data in data.get('prompt_identifiers', []):
        identifier = prompt_data['identifier']
        cursor.execute("SELECT id, concept, status FROM prompts WHERE identifier = ?", (identifier,))
        existing = cursor.fetchone()
        if existing:
            changes['updated_prompts'].append({
                'identifier': identifier,
                'existing_concept': existing['concept'],
                'new_concept': prompt_data['concept']
            })
        else:
            changes['new_prompts'].append({
                'identifier': identifier,
                'concept': prompt_data['concept']
            })

    for key in data.get('wildcard_library', {}).keys():
        normalized_key = normalize_wildcard_key(key)
        cursor.execute("SELECT id FROM wildcard_definitions WHERE wildcard_key = ?", (normalized_key,))
        existing = cursor.fetchone()
        if existing:
            changes['existing_wildcards'].append(normalized_key)
        else:
            changes['new_wildcards'].append(normalized_key)

    return changes
