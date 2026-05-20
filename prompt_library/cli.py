import argparse
import json
import sys
from .db import initialize, reset, get_connection
from .importer import import_json_file, diff_import
from .renderer import render_prompt, render_all_styles


def cmd_init(args):
    conn = initialize(args.db)
    print(f"Database initialized at {args.db}")


def cmd_reset(args):
    if not args.force:
        confirm = input("This will delete all data. Continue? [y/N] ")
        if confirm.lower() != 'y':
            print("Aborted.")
            return
    conn = reset(args.db)
    print(f"Database reset at {args.db}")


def cmd_import(args):
    result = import_json_file(args.file, args.db, dry_run=args.dry_run)
    if args.dry_run:
        print(f"DRY RUN: Would import {result['prompts_imported']} prompts and {result['wildcards_imported']} wildcards")
    else:
        print(f"Imported {result['prompts_imported']} prompts and {result['wildcards_imported']} wildcards")


def cmd_diff(args):
    changes = diff_import(args.file, args.db)
    print(json.dumps(changes, indent=2))


def cmd_render(args):
    try:
        if args.all_styles:
            results = render_all_styles(args.prompt, args.seed, args.overrides, args.db)
            print(json.dumps(results, indent=2))
        else:
            result = render_prompt(args.prompt, args.style, args.seed, args.overrides, args.db)
            print(json.dumps(result, indent=2))
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_list_prompts(args):
    conn = get_connection(args.db)
    cursor = conn.cursor()
    query = "SELECT identifier, concept, status FROM prompts"
    params = []
    if args.status:
        query += " WHERE status = ?"
        params.append(args.status)
    query += " ORDER BY identifier"
    cursor.execute(query, params)
    rows = cursor.fetchall()
    for row in rows:
        print(f"{row['identifier']}: {row['concept']} [{row['status']}]")


def cmd_list_styles(args):
    conn = get_connection(args.db)
    cursor = conn.cursor()
    cursor.execute("SELECT identifier, syntax_family, negative_prompt_strategy FROM prompt_style_profiles ORDER BY identifier")
    rows = cursor.fetchall()
    for row in rows:
        print(f"{row['identifier']}: {row['syntax_family']} (negative: {row['negative_prompt_strategy']})")


def cmd_list_wildcards(args):
    conn = get_connection(args.db)
    cursor = conn.cursor()
    cursor.execute("SELECT wd.wildcard_key, wd.status, COUNT(wv.id) as value_count FROM wildcard_definitions wd LEFT JOIN wildcard_values wv ON wd.id = wv.wildcard_definition_id GROUP BY wd.id ORDER BY wd.wildcard_key")
    rows = cursor.fetchall()
    for row in rows:
        print(f"{row['wildcard_key']}: {row['value_count']} values [{row['status']}]")


def cmd_search(args):
    conn = get_connection(args.db)
    cursor = conn.cursor()
    query = """
        SELECT p.identifier, p.concept, p.status
        FROM prompts p
        WHERE p.concept LIKE ? OR p.identifier LIKE ?
        ORDER BY p.identifier
    """
    pattern = f"%{args.query}%"
    cursor.execute(query, (pattern, pattern))
    rows = cursor.fetchall()
    for row in rows:
        print(f"{row['identifier']}: {row['concept']} [{row['status']}]")


def cmd_validate(args):
    conn = get_connection(args.db)
    cursor = conn.cursor()
    cursor.execute("SELECT pt.id, pt.positive_template, p.identifier as prompt_id FROM prompt_templates pt JOIN prompts p ON pt.prompt_id = p.id WHERE pt.enabled = 1")
    templates = cursor.fetchall()
    errors = []
    for template in templates:
        from .wildcards import find_unbound_wildcards
        cursor.execute(
            "SELECT wd.wildcard_key FROM prompt_wildcard_bindings pwb JOIN wildcard_definitions wd ON pwb.wildcard_definition_id = wd.id WHERE pwb.prompt_id = (SELECT id FROM prompts WHERE identifier = ?)",
            (template['prompt_id'],)
        )
        bound_keys = {row['wildcard_key'] for row in cursor.fetchall()}
        unbound = find_unbound_wildcards(template['positive_template'], bound_keys)
        if unbound:
            errors.append(f"Template {template['id']} ({template['prompt_id']}): unbound wildcards {unbound}")
    if errors:
        print("Validation errors:")
        for error in errors:
            print(f"  - {error}")
    else:
        print("All templates valid.")


def main():
    parser = argparse.ArgumentParser(description="Prompt Library CLI")
    parser.add_argument('--db', default=None, help="Path to SQLite database")

    subparsers = parser.add_subparsers(dest='command', help="Command to run")

    init_parser = subparsers.add_parser('init', help="Initialize database")
    init_parser.set_defaults(func=cmd_init)

    reset_parser = subparsers.add_parser('reset', help="Reset database")
    reset_parser.add_argument('--force', action='store_true', help="Skip confirmation")
    reset_parser.set_defaults(func=cmd_reset)

    import_parser = subparsers.add_parser('import', help="Import JSON file")
    import_parser.add_argument('file', help="Path to JSON file")
    import_parser.add_argument('--dry-run', action='store_true', help="Show what would be imported")
    import_parser.set_defaults(func=cmd_import)

    diff_parser = subparsers.add_parser('diff', help="Show diff before import")
    diff_parser.add_argument('file', help="Path to JSON file")
    diff_parser.set_defaults(func=cmd_diff)

    render_parser = subparsers.add_parser('render', help="Render a prompt")
    render_parser.add_argument('prompt', help="Prompt identifier")
    render_parser.add_argument('--style', help="Style profile identifier")
    render_parser.add_argument('--all-styles', action='store_true', help="Render all styles")
    render_parser.add_argument('--seed', type=int, help="Random seed for wildcard selection")
    render_parser.add_argument('--overrides', type=json.loads, help="Wildcard overrides as JSON")
    render_parser.set_defaults(func=cmd_render)

    list_prompts_parser = subparsers.add_parser('list-prompts', help="List prompts")
    list_prompts_parser.add_argument('--status', help="Filter by status")
    list_prompts_parser.set_defaults(func=cmd_list_prompts)

    list_styles_parser = subparsers.add_parser('list-styles', help="List style profiles")
    list_styles_parser.set_defaults(func=cmd_list_styles)

    list_wildcards_parser = subparsers.add_parser('list-wildcards', help="List wildcards")
    list_wildcards_parser.set_defaults(func=cmd_list_wildcards)

    search_parser = subparsers.add_parser('search', help="Search prompts")
    search_parser.add_argument('query', help="Search query")
    search_parser.set_defaults(func=cmd_search)

    validate_parser = subparsers.add_parser('validate', help="Validate templates")
    validate_parser.set_defaults(func=cmd_validate)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return
    args.func(args)


if __name__ == '__main__':
    main()
