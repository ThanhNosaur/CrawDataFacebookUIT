import json, sys, io
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
data = json.load(open("data/raw_posts_latest.json", "r", encoding="utf-8"))
print(f"Total posts: {len(data)}\n")
for i, p in enumerate(data):
    text = p.get("text", "")[:150].replace("\n", " ")
    print(f"[{i}] PAGE={p['page']} | TIME={p.get('time','')} | TEXT={text}")
    print()
