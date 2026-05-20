import re
from collections import defaultdict

WILDCARD_PATTERN = re.compile(r'\{(\w+)\}')
DYNAMIC_WILDCARD_PATTERN = re.compile(r'__([\w]+)__')


def extract_wildcard_keys(text):
    keys = set()
    keys.update(WILDCARD_PATTERN.findall(text))
    keys.update(DYNAMIC_WILDCARD_PATTERN.findall(text))
    return keys


def extract_all_wildcards_from_templates(templates):
    all_keys = set()
    for template in templates:
        if isinstance(template, dict):
            for field in ['positive_template', 'negative_template']:
                if field in template and template[field]:
                    all_keys.update(extract_wildcard_keys(template[field]))
        elif isinstance(template, str):
            all_keys.update(extract_wildcard_keys(template))
    return all_keys - {'concept'}


def normalize_wildcard_key(key):
    key = key.strip().lower()
    key = key.replace('-', '_')
    key = key.replace(' ', '_')
    return key


def detect_wildcard_candidates(text):
    candidates = []
    for match in WILDCARD_PATTERN.finditer(text):
        candidates.append({
            'key': match.group(1),
            'start': match.start(),
            'end': match.end(),
            'full_match': match.group(0)
        })
    for match in DYNAMIC_WILDCARD_PATTERN.finditer(text):
        candidates.append({
            'key': match.group(1),
            'start': match.start(),
            'end': match.end(),
            'full_match': match.group(0)
        })
    return candidates


def replace_wildcards(text, replacements):
    result = text
    for key, value in replacements.items():
        result = result.replace('{' + key + '}', str(value))
        result = result.replace('{' + key.lower() + '}', str(value))
        result = result.replace('__' + key + '__', str(value))
        result = result.replace('__' + key.lower() + '__', str(value))
    return result


def find_unbound_wildcards(template, bound_keys):
    found = extract_wildcard_keys(template)
    found.discard('concept')
    return found - set(bound_keys)
