import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

# Sources
sources = [
    "https://iptv-org.github.io/iptv/languages/ara.m3u",
    "https://iptv-org.github.io/iptv/languages/fra.m3u"
]

output_file = "combined.m3u"
MAX_WORKERS = 20  # Number of threads for parallel testing

def check_url(url):
    try:
        r = requests.head(url, timeout=5)
        return r.status_code == 200
    except:
        return False

# Collect all streams first
streams = []

for src in sources:
    print(f"Processing source: {src}")
    r = requests.get(src)
    lines = r.text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("#EXTINF"):
            extinf = line
            url = lines[i + 1].strip()
            streams.append((extinf, url))

print(f"Total streams found: {len(streams)}")
live_streams = []

# Test streams in parallel
with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
    future_to_stream = {executor.submit(check_url, url): (extinf, url) for extinf, url in streams}
    for future in as_completed(future_to_stream):
        extinf, url = future_to_stream[future]
        try:
            if future.result():
                live_streams.append((extinf, url))
                print(f"✓ LIVE: {url}")
            else:
                print(f"✗ DEAD: {url}")
        except Exception as e:
            print(f"✗ ERROR: {url} ({e})")

# Write combined M3U
with open(output_file, "w") as out:
    out.write("#EXTM3U\n\n")
    for extinf, url in live_streams:
        out.write(f"{extinf}\n")
        out.write(f"{url}\n")
