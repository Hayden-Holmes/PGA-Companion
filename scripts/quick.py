# paste this into a quick script or run in python interactive mode
import json

with open("tools\\payload_output\\StatDetails_tourCodeR_statId120_year2026.json") as f:
    data = json.load(f)

stats = {}
for cat in data["statDetails"]["statCategories"]:
    cat_name = cat["category"]
    for sub in cat.get("subCategories", []):
        for stat in sub.get("stats", []):
            stats[stat["statId"]] = (cat_name, stat["statTitle"])

print(f"Total unique stats: {len(stats)}")
for sid, (cat, title) in sorted(stats.items()):
    print(f'  "{sid}": "{title}",  # {cat}')