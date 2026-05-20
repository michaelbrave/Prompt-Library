import random
import json
from .db import get_connection
from .wildcards import replace_wildcards, extract_wildcard_keys


def get_wildcard_values(cursor, wildcard_key):
    cursor.execute(
        "SELECT wv.value, wv.weight FROM wildcard_values wv "
        "JOIN wildcard_definitions wd ON wv.wildcard_definition_id = wd.id "
        "WHERE wd.wildcard_key = ? AND wd.status = 'active'",
        (wildcard_key,)
    )
    rows = cursor.fetchall()
    if not rows:
        return []
    values = [row['value'] for row in rows]
    weights = [row['weight'] for row in rows]
    return values, weights


def select_wildcard_value(values, weights, seed=None):
    if not values:
        return None
    if seed is not None:
        rng = random.Random(seed)
        return rng.choices(values, weights=weights, k=1)[0]
    return random.choices(values, weights=weights, k=1)[0]


def render_prompt(prompt_identifier, style_profile_identifier=None, seed=None, wildcard_overrides=None, db_path=None):
    conn = get_connection(db_path)
    cursor = conn.cursor()

    cursor.execute("SELECT id, identifier, concept FROM prompts WHERE identifier = ?", (prompt_identifier,))
    prompt = cursor.fetchone()
    if not prompt:
        raise ValueError(f"Prompt '{prompt_identifier}' not found")

    prompt_id = prompt['id']
    concept = prompt['concept']

    if style_profile_identifier:
        cursor.execute(
            "SELECT pt.id, pt.positive_template, pt.negative_template, pt.enabled, psp.identifier as style_identifier "
            "FROM prompt_templates pt "
            "JOIN prompt_style_profiles psp ON pt.style_profile_id = psp.id "
            "WHERE pt.prompt_id = ? AND psp.identifier = ?",
            (prompt_id, style_profile_identifier)
        )
    else:
        cursor.execute(
            "SELECT pt.id, pt.positive_template, pt.negative_template, pt.enabled, psp.identifier as style_identifier "
            "FROM prompt_templates pt "
            "JOIN prompt_style_profiles psp ON pt.style_profile_id = psp.id "
            "WHERE pt.prompt_id = ? AND pt.enabled = 1 "
            "ORDER BY psp.syntax_family",
            (prompt_id,)
        )

    templates = cursor.fetchall()
    if not templates:
        raise ValueError(f"No enabled templates found for prompt '{prompt_identifier}'")

    if style_profile_identifier and not templates:
        raise ValueError(f"No template found for style '{style_profile_identifier}'")

    template = templates[0]
    positive = template['positive_template']
    negative = template['negative_template']
    style_id = template['style_identifier']

    cursor.execute(
        "SELECT wd.wildcard_key FROM prompt_wildcard_bindings pwb "
        "JOIN wildcard_definitions wd ON pwb.wildcard_definition_id = wd.id "
        "WHERE pwb.prompt_id = ?",
        (prompt_id,)
    )
    bound_keys = [row['wildcard_key'] for row in cursor.fetchall()]

    wildcard_values = {}
    wildcard_overrides = wildcard_overrides or {}

    for key in bound_keys:
        if key in wildcard_overrides:
            wildcard_values[key] = wildcard_overrides[key]
        else:
            result = get_wildcard_values(cursor, key)
            if result:
                values, weights = result
                wildcard_values[key] = select_wildcard_value(values, weights, seed)

    wildcard_values['concept'] = concept

    rendered_positive = replace_wildcards(positive, wildcard_values)
    rendered_negative = replace_wildcards(negative, wildcard_values)

    return {
        'prompt_identifier': prompt_identifier,
        'style_profile_identifier': style_id,
        'positive_prompt': rendered_positive,
        'negative_prompt': rendered_negative,
        'wildcard_values': {k: v for k, v in wildcard_values.items() if k != 'concept'},
        'seed': seed
    }


def render_all_styles(prompt_identifier, seed=None, wildcard_overrides=None, db_path=None):
    conn = get_connection(db_path)
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM prompts WHERE identifier = ?", (prompt_identifier,))
    prompt = cursor.fetchone()
    if not prompt:
        raise ValueError(f"Prompt '{prompt_identifier}' not found")

    cursor.execute(
        "SELECT psp.identifier FROM prompt_style_profiles psp "
        "JOIN prompt_templates pt ON pt.style_profile_id = psp.id "
        "WHERE pt.prompt_id = ? AND pt.enabled = 1",
        (prompt['id'],)
    )
    styles = [row['identifier'] for row in cursor.fetchall()]

    results = []
    for style in styles:
        try:
            result = render_prompt(prompt_identifier, style, seed, wildcard_overrides, db_path)
            results.append(result)
        except Exception as e:
            results.append({
                'prompt_identifier': prompt_identifier,
                'style_profile_identifier': style,
                'error': str(e)
            })

    return results
