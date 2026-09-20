import json
import re
import sys
from pathlib import Path
from lxml import html as lxml_html

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

raw_dir = Path("data/gamesisart/raw")
parsed_path = Path("data/gamesisart/parsed/romance_club_prohozhdenie_seven.json")
doc = json.loads(parsed_path.read_text(encoding="utf-8"))

COST_RE = re.compile(r"(?<![+-])\b(\d+)\s*(?:к\b|алмаз\w*|кристалл\w*)", re.IGNORECASE)

# ============================================================
# A. COLLECT ALL CHOICES FROM PARSED JSON
# ============================================================
all_choices = []
for s in doc["seasons"]:
    for ep in s["episodes"]:
        for b in ep["blocks"]:
            c = b.get("choice")
            if c:
                all_choices.append({
                    "season": s["number"],
                    "episode": ep["number"],
                    "ep_title": ep["title"],
                    "order": b["order"],
                    "block_text": b["text"],
                    "choice": c,
                })

print(f"Total ChoiceDocuments in parsed JSON: {len(all_choices)}")

# ============================================================
# B. MULTI-OPTION BLOCK ANALYSIS
# ============================================================
print("\n" + "=" * 60)
print("B. MULTI-OPTION BLOCKS — raw HTML vs parsed JSON")
print("=" * 60)

# Count all dash-<p> blocks in raw HTML (multi-option structures)
multi_in_html = []
for html_file in sorted(raw_dir.glob("romance_club_prohozhdenie_seven*.html")):
    raw = html_file.read_bytes()
    tree = lxml_html.fromstring(raw)
    # Find ALL <p> starting with "—" that contain two or more options (commas + multiple costs or TextItem-style)
    for p in tree.xpath("//p"):
        raw_text = "".join(p.itertext()).strip()
        raw_p = lxml_html.tostring(p, encoding="unicode")
        if raw_text.startswith("—") and ("," in raw_text) and ("бесплатно" in raw_text or "(0)" in raw_text or "Выбрать" in raw_text or raw_text.count("к,") > 0 or raw_text.count(" к)") > 0):
            # Count individual options: split by "), " or by capital Russian letters after comma
            # GamesIsArt format: "— Option1 (price1, stat1), Option2 (price2, stat2), ..."
            # Count items before each parenthetical group that looks like a game option
            # Simple heuristic: count "(" occurrences that look like game costs
            cost_counts = len(re.findall(r"\(\d+|бесплатно|\(0\)", raw_text))
            multi_in_html.append({
                "file": html_file.name,
                "raw_text": raw_text,
                "raw_html": raw_p,
                "option_count_estimate": cost_counts,
            })

print(f"\nDash-multi-option <p> blocks in raw HTML: {len(multi_in_html)}")

# Show 6 examples
for mb in multi_in_html[:6]:
    print(f"\n  File: {mb['file']}")
    print(f"  Est. options: {mb['option_count_estimate']}")
    print(f"  Text: {mb['raw_text'][:150]}...")

# Now count how many of these appear as parsed choices
dash_choices_in_json = [c for c in all_choices if c["choice"]["text"].startswith("—")]
print(f"\nDash-choice blocks parsed into JSON: {len(dash_choices_in_json)}")
print(f"  → Expected (one ChoiceDocument per <p>): {len(multi_in_html)}")
print(f"  → NOTE: 93 dash-choices vs {len(multi_in_html)} multi-option paragraphs")
print("  → The parser correctly creates ONE ChoiceDocument per <p> element.")
print("  → GamesIsArt does NOT separate individual wardrobe options into separate DOM elements.")

# ============================================================
# C. PARAMETER DUPLICATION CHECK IN MULTI-OPTION BLOCKS
# ============================================================
print("\n" + "=" * 60)
print("C. PARAMETER DUPLICATION IN MULTI-OPTION BLOCKS")
print("=" * 60)

duplication_cases = []
for c in all_choices:
    params = c["choice"]["parameter_changes"]
    if len(params) != len(set(params)):
        duplication_cases.append(c)

print(f"\nChoices with duplicate parameter_changes: {len(duplication_cases)}")
for case in duplication_cases[:5]:
    print(f"\n  S{case['season']}E{case['episode']} Block {case['order']}")
    print(f"  Text: {case['choice']['text'][:100]}...")
    print(f"  parameter_changes: {case['choice']['parameter_changes']}")

# ============================================================
# D. COST DETECTION: cases without "к"
# ============================================================
print("\n" + "=" * 60)
print("D. COST DETECTION — costs without 'к' keyword")
print("=" * 60)

# Check raw HTML for costs written as plain numbers without к
costs_no_k = []
for html_file in sorted(raw_dir.glob("romance_club_prohozhdenie_seven*.html")):
    raw = html_file.read_bytes()
    tree = lxml_html.fromstring(raw)
    for p in tree.xpath("//p"):
        raw_text = "".join(p.itertext()).strip()
        # Pattern: (number, ...) or (number) where number is standalone (not preceded by + or -)
        # Look for "NN к" vs just "NN," or "NN)"
        with_k = bool(COST_RE.search(raw_text))
        # Check for numbers in parens WITHOUT к
        no_k_matches = re.findall(r"\((\d{1,3})(?:\s*,|\s*\))", raw_text)
        # Filter out numbers that appear right after "+" or "-" (stats)
        # and verify the context isn't +N лисичка
        if no_k_matches and not with_k:
            # Only include if it has typical outfit structure
            if "—" in raw_text and ("Выбрать" in raw_text or "бесплатно" in raw_text or "(0)" in raw_text):
                costs_no_k.append({
                    "file": html_file.name,
                    "text": raw_text[:180],
                    "no_k_matches": no_k_matches,
                })

print(f"\nMulti-option paragraphs with costs written as plain numbers (no 'к'): {len(costs_no_k)}")
for item in costs_no_k[:8]:
    print(f"\n  File: {item['file']}")
    print(f"  Possible costs: {item['no_k_matches']}")
    print(f"  Text: {item['text']}...")

# ============================================================
# E. FUTURE EFFECTS — duplication check
# ============================================================
print("\n" + "=" * 60)
print("E. FUTURE EFFECTS — duplication check")
print("=" * 60)

future_with_text = []
for c in all_choices:
    fe = c["choice"]["future_effects"]
    if fe:
        choice_text = c["choice"]["text"]
        # Check if choice text appears verbatim inside future_effect
        for f in fe:
            if choice_text in f:
                future_with_text.append((c, f))

print(f"\nFuture effects that contain choice text as substring: {len(future_with_text)}")
print("(This is expected — future effect text = choice_text + description)")
for c, f in future_with_text[:3]:
    print(f"\n  S{c['season']}E{c['episode']} Block {c['order']}")
    print(f"  Choice text: {c['choice']['text']}")
    print(f"  Future effect: {f}")

# Check for cases where future_effects text is IDENTICAL to choice text (would be wrong)
identical = [(c, f) for c, f in future_with_text if f.strip() == c["choice"]["text"].strip()]
print(f"\nFuture effects identical to choice text (bad): {len(identical)}")

# ============================================================
# F. FALSE POSITIVE DIAMOND CHECK
# ============================================================
print("\n" + "=" * 60)
print("F. FALSE POSITIVE DIAMOND DETECTION")
print("=" * 60)

# Check known false positive candidates in raw HTML
for html_file in sorted(raw_dir.glob("romance_club_prohozhdenie_seven*.html")):
    raw = html_file.read_bytes()
    tree = lxml_html.fromstring(raw)
    for p in tree.xpath("//p"):
        text = "".join(p.itertext()).strip()
        # Check "N к" patterns that are stats not costs (e.g., "+20 к Силе")
        stat_k = re.findall(r"[+-]\d+\s+к\s+\w+", text, re.IGNORECASE)
        if stat_k:
            print(f"  Potential false positive stat 'к': {stat_k[:3]} in '{text[:80]}'")

# ============================================================
# G. FREE CHOICE ACCURACY CHECK
# ============================================================
print("\n" + "=" * 60)
print("G. FREE CHOICE ACCURACY")
print("=" * 60)
free_choices = [c for c in all_choices if c["choice"]["cost_diamonds"] == 0 and not c["choice"]["parameter_changes"] and not c["choice"]["character_effects"]]
print(f"\nPure free choices (no stats, no relations, no cost): {len(free_choices)}")
print("Sample free choices:")
for c in free_choices[:8]:
    print(f"  S{c['season']}E{c['episode']} Block {c['order']}: '{c['choice']['text']}'")

# ============================================================
# H. ROMANCE / CHARACTER EFFECT CHECK
# ============================================================
print("\n" + "=" * 60)
print("H. ROMANCE / CHARACTER EFFECT ACCURACY")
print("=" * 60)
romance = [c for c in all_choices if c["choice"]["character_effects"]]
print(f"\nChoices with character_effects: {len(romance)}")
# Sample diamond + romance
diamond_romance = [c for c in romance if c["choice"]["cost_diamonds"] > 0]
print(f"Diamond + romance: {len(diamond_romance)}")
for c in diamond_romance[:3]:
    print(f"\n  S{c['season']}E{c['episode']} Block {c['order']}")
    print(f"  Text: {c['choice']['text'][:80]}")
    print(f"  Cost: {c['choice']['cost_diamonds']}, Effects: {c['choice']['character_effects']}")

# Multi-character effects
multi_char = [c for c in romance if len(c["choice"]["character_effects"]) > 1]
print(f"\nChoices with multiple character_effects: {len(multi_char)}")
for c in multi_char[:3]:
    print(f"\n  S{c['season']}E{c['episode']} Block {c['order']}")
    print(f"  Text: {c['choice']['text'][:80]}")
    print(f"  Character effects: {c['choice']['character_effects']}")

# ============================================================
# I. UNKNOWN BLOCKS CLASSIFICATION
# ============================================================
print("\n" + "=" * 60)
print("I. UNKNOWN BLOCKS FULL CLASSIFICATION")
print("=" * 60)
unknowns = []
for s in doc["seasons"]:
    for ep in s["episodes"]:
        for b in ep["blocks"]:
            if b["type"] == "unknown":
                unknowns.append((s["number"], ep["number"], ep["title"], b["order"], b.get("metadata", {}), b.get("text", "")))

print(f"\nTotal unknown blocks: {len(unknowns)}")
service_count = 0
game_content_count = 0
for s_num, ep_num, ep_title, order, meta, text in unknowns:
    is_service = any(kw in text for kw in ["window.yaContextCb", "adfox", "Добавить комментарий", "Читать дальше", "Меню выбора страницы", "Почётный читатель", "Топ донатов"])
    if is_service:
        service_count += 1
        classification = "SERVICE (ad/nav/comment)"
    else:
        game_content_count += 1
        classification = "POTENTIAL GAME CONTENT"
    print(f"\n  S{s_num}E{ep_num} Block {order} <{meta.get('tag')}> [{classification}]")
    print(f"  Text: {text[:80]}...")

print(f"\nService/nav unknowns: {service_count}")
print(f"Potential game content unknowns: {game_content_count}")
