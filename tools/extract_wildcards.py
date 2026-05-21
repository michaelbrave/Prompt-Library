import sqlite3
import re
import json
import argparse
from collections import defaultdict, Counter

DB_PATH = "data/prompts.db"

CATEGORY_PATTERNS = {
    "camera_angle": [
        r'\b(close-?up|medium shot|wide-?angle|low-?angle|high-?angle|eye-?level|three-?quarter|profile|side view|frontal|overhead|tracking shot|panoramic|full body|half body|portrait shot)\b',
        r'\b(\d+mm\s+(?:lens|portrait|wide|standard|telephoto|macro))\b',
        r'\b(f/\d+(?:\.\d+)?(?:\s+RF)?(?:\s+lens)?)\b',
        r'\b(shallow\s+depth\s+of\s+field|deep\s+depth\s+of\s+field|large\s+depth\s+of\s+field|bokeh)\b',
        r'\b(fish-?eye|fisheye)\b',
    ],
    "lighting": [
        r'\b(golden\s+hour|blue\s+hour|rim\s+light|backlight|backlit|frontal\s+light|side\s+light|overhead\s+light|ambient\s+light|natural\s+light|studio\s+light)\b',
        r'\b(dramatic\s+light|soft\s+light|hard\s+light|diffused\s+light|directional\s+light|volumetric\s+light)\b',
        r'\b(cinematic\s+lighting|warm\s+lighting|cool\s+lighting|golden\s+light|cinematic\s+studio\s+lighting)\b',
        r'\b(long\s+shadows|deep\s+shadows|soft\s+shadows|harsh\s+shadows|chiaroscuro)\b',
        r'\b(lens\s+flare|light\s+bloom|light\s+leak|god\s+rays|specular\s+highlights|cinematic\s+lens\s+bloom|holographic\s+light\s+leaks)\b',
        r'\b(high\s+contrast|low-?key|warm\s+tones|cool\s+tones|color\s+grading)\b',
        r'\b(moody\s+lighting|romantic\s+dim\s+lighting|dim\s+lighting)\b',
        r'\b(moonlight)\b',
    ],
    "style_medium": [
        r'\b(oil\s+painting|watercolor|watercolor\s+painting|acrylic\s+painting|charcoal\s+sketch|pencil\s+sketch|ink\s+drawing|gouache)\b',
        r'\b(digital\s+(?:illustration|art|painting|rendering))\b',
        r'\b(photorealistic|hyper-?realistic|ultra-?realistic|semi-?realistic)\b',
        r'\b(photography|portrait\s+photography|fashion\s+photography|food\s+photography|product\s+shot|studio\s+portrait)\b',
        r'\b(impressionistic|expressionism|impressionist|abstract|surreal|surrealism)\b',
        r'\b(anime-?inspired|cel-?shaded|manga\s+style|comic\s+style|grunge\s+comic|90s\s+anime)\b',
        r'\b(cyberpunk|steampunk|noir|film\s+noir|pin-?up\s+art)\b',
        r'\b(impasto|brushstroke|painterly|textured\s+canvas)\b',
        r'\b(black\s+and\s+white|monochrome|grayscale)\b',
        r'\b(film\s+photography|35mm\s+film|slide\s+film|Polaroid)\b',
        r'\b(minimalist\s+(?:line\s+art|illustration|sketch)|minimalist\s+design|futuristic\s+minimalism)\b',
        r'\b(vector\s+illustration|flat\s+illustration)\b',
        r'\b(sumi-?e|calligraphic)\b',
        r'\b(pixel\s+art\s+style|pixel\s+art)\b',
        r'\b(hypermaximalist|neoclassical)\b',
        r'\b(digital\s+pointillism|electronic\s+glitch\s+aesthetic)\b',
        r'\b(minimal\s+masterpiece)\b',
    ],
    "mood_atmosphere": [
        r'\b(dreamy|ethereal|moody|serene|melancholic|dramatic|cinematic|epic)\b',
        r'\b(intimate|romantic|nostalgic|contemplative|mysterious|haunting)\b',
        r'\b(vibrant|vivid|warm|cool|gloomy|dark|bright|luminous)\b',
        r'\b(atmospheric|atmosphere|ambiance)\b',
        r'\b(dream-?like|mystical|whimsical|tranquil|enchanting)\b',
        r'\b(cold\s+atmosphere|cold\s+tones)\b',
    ],
    "location_environment": [
        r'\b(subway\s+(?:car|station)|train\s+station|metro)\b',
        r'\b(beach|shoreline|ocean|seaside|coastal|tropical\s+beach)\b',
        r'\b(mountain|mountains|peak|mountain\s+range|cliff|cliffs|valley)\b',
        r'\b(urban|city|downtown|street|alley|alleyway|cobalt-?blue\s+alleyway|cyberpunk\s+city)\b',
        r'\b(caf[eé]|coffee\s+shop|ramen\s+shop|ice\s+cream\s+parlor)\b',
        r'\b(garden|terrace|park|forest|woods|jungle)\b',
        r'\b(studio|photo\s+studio|indoor\s+studio)\b',
        r'\b(desert|wasteland|dunes)\b',
        r'\b(underwater|submerged)\b',
        r'\b(mirrored\s+(?:hallway|corridor)|mirrored\s+corridor)\b',
        r'\b(mediterranean|coastal\s+village)\b',
        r'\b(snow-?capped|snowy|frosty)\b',
        r'\b(misty|foggy|hazy|swirling\s+mist)\b',
        r'\b(penthouse|master\s+bedroom|bedroom)\b',
        r'\b(on\s+desk|desk)\b',
    ],
    "clothing": [
        r'\b(denim\s+(?:jacket|shirt|shorts)|jeans|chinos|cargo\s+pants)\b',
        r'\b(t-?shirt|crew-?neck|graphic\s+t-?shirt|white\s+t-?shirt)\b',
        r'\b(blouse|white\s+blouse|off-?the-?shoulder\s+blouse)\b',
        r'\b(dress|floral\s+dress|white\s+dress|black\s+dress|midi\s+skirt|mini\s+skirt)\b',
        r'\b(jacket|denim\s+jacket|hiking\s+jacket|linen\s+shirt|hoodie|zip-?up\s+hoodie)\b',
        r'\b(sneakers|skate\s+sneakers|boots|trekking\s+boots|flip-?flops|heels|high-?heel\s+pumps)\b',
        r'\b(hat|baseball\s+cap|fedora|wide-?brim\s+hat|soft\s+fabric\s+hat)\b',
        r'\b(sunglasses|dark\s+sunglasses|aviator\s+sunglasses)\b',
        r'\b(suit|suit\s+jacket|dark\s+suit|blazer|ivory\s+blazer)\b',
        r'\b(shorts|denim\s+shorts|khaki\s+shorts|athletic\s+shorts)\b',
        r'\b(veil|wedding\s+veil|tulle\s+skirt|silk\s+gown|bridal\s+gown)\b',
        r'\b(overalls|tank\s+top|camisole|crop\s+tee|long-?sleeve\s+top)\b',
        r'\b(socks|crew\s+socks|ribbed\s+socks|stockings|sheer\s+stockings)\b',
        r'\b(earrings|pearl\s+earrings|diamond\s+earrings|circular\s+earrings)\b',
        r'\b(bracelet|beaded\s+bracelet|pearl\s+bracelet)\b',
        r'\b(headphones|over-?ear\s+headphones|yellow\s+headphones)\b',
        r'\b(backpack|trekking\s+backpack)\b',
        r'\b(cloak|red\s+cloak|hooded\s+garment|trench\s+coat)\b',
        r'\b(kimono|flowered\s+kimono|traditional\s+kimono)\b',
    ],
    "person_subject": [
        r'\b(young\s+(?:man|woman|male|female|model|bride))\b',
        r'\b(muscular\s+(?:man|male|model|young\s+man))\b',
        r'\b(handsome\s+(?:young\s+)?man)\b',
        r'\b(beautiful\s+(?:young\s+)?woman)\b',
        r'\b(confident\s+(?:female\s+)?model)\b',
        r'\b(mature\s+(?:bald\s+)?man)\b',
        r'\b(rugged\s+man)\b',
        r'\b(fit\s+man)\b',
        r'\b(female\s+model|male\s+model)\b',
        r'\b(bald\s+man)\b',
        r'\b(bride)\b',
        r'\b(musician)\b',
        r'\b(adventurous\s+man)\b',
        r'\b(regal\s+woman|queenly\s+figure)\b',
    ],
    "hair": [
        r'\b(long\s+(?:dark|wavy|blonde|brown|curly|ginger)\s+hair)\b',
        r'\b(short\s+(?:dark|brown|blonde)\s+hair)\b',
        r'\b(wavy\s+(?:brown|blonde|dark)\s+hair)\b',
        r'\b(messy\s+bun|tousled\s+hair|windswept\s+hair|slicked\s+back)\b',
        r'\b(dark\s+hair|blonde\s+hair|brown\s+hair|ginger\s+hair|red\s+hair)\b',
        r'\b(bob\s+hair|short\s+bob)\b',
        r'\b(wet-?looking\s+(?:dark\s+)?waves|wet\s+hair)\b',
        r'\b(tied\s+back|ponytail)\b',
        r'\b(bangs|wispy\s+bangs)\b',
    ],
    "action_pose": [
        r'\b(standing|standing\s+with\s+arms|standing\s+still|standing\s+relaxed)\b',
        r'\b(sitting|seated|sitting\s+cross-?legged|sitting\s+comfortably|slumped)\b',
        r'\b(leaning|leaning\s+casually)\b',
        r'\b(walking|strolling|walking\s+barefoot)\b',
        r'\b(gazing|gazing\s+upward|gazing\s+back|gazing\s+at\s+the\s+horizon)\b',
        r'\b(looking\s+(?:up|down|directly|away|upward|toward))\b',
        r'\b(smiling|grinning|gentle\s+smile)\b',
        r'\b(arms\s+outstretched|arms\s+crossed|hands\s+clasped)\b',
        r'\b(head\s+tilted|tilted\s+head)\b',
        r'\b(relaxed\s+pose|contemplative\s+pose|shy\s+pose)\b',
        r'\b(holding|holding\s+a\s+book|holding\s+a\s+banana)\b',
    ],
    "color_palette": [
        r'\b(warm\s+(?:orange|tones|hues|glow))\b',
        r'\b(cool\s+(?:cyan|tones|blue))\b',
        r'\b(golden\s+(?:orange|yellow|glow|hues))\b',
        r'\b(deep\s+(?:blue|black|shadows))\b',
        r'\b(bright\s+(?:yellow|sunlight|daylight))\b',
        r'\b(neon\s+(?:yellow|accents|glow))\b',
        r'\b(pastel\s+(?:background|blue|pink|colors))\b',
        r'\b(terracotta|ochre|sepia)\b',
    ],
    "composition": [
        r'\b(symmetrical\s+composition|centered\s+composition|dynamic\s+composition)\b',
        r'\b(tight\s+composition|tight\s+framing)\b',
        r'\b(split-?color\s+background|solid\s+background|neutral\s+background)\b',
        r'\b(blurred\s+background|soft-?focus\s+background|out-?of-?focus\s+background)\b',
        r'\b(reflection|mirror\s+reflection|glossy\s+surface)\b',
        r'\b(canyon-?like\s+effect|layered\s+depth)\b',
        r'\b(forced\s+perspective|close\s+forced\s+perspective)\b',
    ],
}

STOP_WORDS = {
    'a', 'an', 'the', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
    'of', 'with', 'by', 'from', 'is', 'are', 'was', 'were', 'be', 'been',
    'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would',
    'could', 'should', 'may', 'might', 'shall', 'can', 'need', 'dare',
    'ought', 'used', 'it', 'its', 'this', 'that', 'these', 'those', 'i',
    'you', 'he', 'she', 'we', 'they', 'what', 'which', 'who', 'whom',
    'whose', 'where', 'when', 'why', 'how', 'all', 'each', 'every',
    'both', 'few', 'many', 'much', 'some', 'any', 'no', 'not', 'only',
    'own', 'same', 'so', 'than', 'too', 'very', 'just', 'also', 'now',
    'here', 'there', 'then', 'once', 'if', 'as', 'her', 'his', 'my',
    'your', 'our', 'their', 'about', 'into', 'through', 'during',
    'before', 'after', 'above', 'below', 'between', 'under', 'again',
    'further', 'while', 'against', 'such', 'up', 'out', 'off', 'over',
}


def get_all_prompt_text(conn):
    texts = []

    cursor = conn.execute("SELECT positive_template FROM prompt_templates WHERE enabled = 1")
    texts.extend([row[0] for row in cursor.fetchall() if row[0]])

    cursor = conn.execute("SELECT negative_template FROM prompt_templates WHERE negative_template IS NOT NULL AND negative_template != ''")
    texts.extend([row[0] for row in cursor.fetchall() if row[0]])

    cursor = conn.execute("SELECT metadata FROM prompts WHERE metadata IS NOT NULL AND metadata != '{}'")
    for row in cursor:
        try:
            meta = json.loads(row[0])
            if 'original_prompt' in meta:
                texts.append(meta['original_prompt'])
            if 'structured_fields' in meta:
                for field_val in meta['structured_fields'].values():
                    texts.append(field_val)
        except (json.JSONDecodeError, TypeError):
            pass

    return texts


def extract_wildcards(texts):
    results = defaultdict(lambda: defaultdict(int))

    for text in texts:
        if not text:
            continue
        text_lower = text.lower()

        for category, patterns in CATEGORY_PATTERNS.items():
            for pattern in patterns:
                for match in re.finditer(pattern, text_lower):
                    term = match.group(0).strip()
                    if term and len(term) > 2:
                        results[category][term] += 1

    return results


def normalize_term(term):
    term = re.sub(r'\s+', ' ', term).strip()
    term = term.strip(',.;:')
    return term


def insert_wildcards(conn, extracted):
    cursor = conn.cursor()

    for category, terms in extracted.items():
        filtered = {normalize_term(t): c for t, c in terms.items() if c >= 2}

        if not filtered:
            continue

        cursor.execute(
            "INSERT OR IGNORE INTO wildcard_definitions (wildcard_key, status, notes, created_at, updated_at) VALUES (?, 'active', ?, datetime('now'), datetime('now'))",
            (category, f"Auto-extracted from prompt library")
        )
        cursor.execute("SELECT id FROM wildcard_definitions WHERE wildcard_key = ?", (category,))
        def_row = cursor.fetchone()
        if not def_row:
            continue
        def_id = def_row[0]

        for term, count in sorted(filtered.items(), key=lambda x: -x[1]):
            weight = min(count / 5.0, 2.0)
            cursor.execute(
                "INSERT OR IGNORE INTO wildcard_values (wildcard_definition_id, value, weight, notes, created_at) VALUES (?, ?, ?, ?, datetime('now'))",
                (def_id, term, round(weight, 2), f"found in {count} prompts")
            )

    conn.commit()


def main(apply=False):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    texts = get_all_prompt_text(conn)
    print(f"Scanning {len(texts)} text sources...")

    extracted = extract_wildcards(texts)

    print(f"\nExtracted wildcard categories:")
    total_terms = 0
    for category, terms in sorted(extracted.items()):
        filtered = {normalize_term(t): c for t, c in terms.items() if c >= 2}
        print(f"  {category}: {len(filtered)} terms (from {len(terms)} raw matches)")
        total_terms += len(filtered)
        for term, count in sorted(filtered.items(), key=lambda x: -x[1])[:5]:
            print(f"    - {term} ({count}x)")
        if len(filtered) > 5:
            print(f"    ... and {len(filtered) - 5} more")

    print(f"\nTotal unique wildcard terms: {total_terms}")

    if apply:
        insert_wildcards(conn, extracted)
    else:
        print("\nDry run - rerun with --apply to write wildcard values to the database.")

    cursor = conn.execute("SELECT wd.wildcard_key, COUNT(wv.id) as value_count FROM wildcard_definitions wd LEFT JOIN wildcard_values wv ON wd.id = wv.wildcard_definition_id GROUP BY wd.id ORDER BY wd.wildcard_key")
    print(f"\nWildcard definitions in database:")
    for row in cursor:
        print(f"  {row[0]}: {row[1]} values")

    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract wildcard candidates from the prompt database.")
    parser.add_argument("--apply", action="store_true", help="Write extracted wildcard values to the database")
    args = parser.parse_args()
    main(apply=args.apply)
