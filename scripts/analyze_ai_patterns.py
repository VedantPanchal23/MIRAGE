import re

with open('scripts/build_report_docx.py', 'r', encoding='utf-8') as f:
    text = f.read()

# Common AI detector trigger phrases:
ai_triggers = [
    'paradigm shift', 'crucial', 'furthermore', 'moreover', 'testament',
    'delve', 'beacon', 'realm', 'tapestry', 'revolutioniz', 'in conclusion',
    'it is important to note', 'rapidly evolving', 'cornerstone', 'holistic',
    'underscores', 'fosters', 'pivotal', 'seamless', 'game-changer',
    'in recent years', 'transformative', 'at the forefront', 'it is worth noting'
]

matches = []
for line_num, line in enumerate(text.splitlines(), start=1):
    for trig in ai_triggers:
        if re.search(r'\b' + trig, line, re.IGNORECASE):
            matches.append((line_num, trig, line.strip()[:80]))

print(f"Total AI buzzword triggers found: {len(matches)}")
for lnum, trig, snippet in matches:
    print(f"Line {lnum} [{trig}]: {snippet}...")
