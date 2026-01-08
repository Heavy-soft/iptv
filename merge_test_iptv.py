import requests
import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# Configuration
sources = [
    "https://iptv-org.github.io/iptv/languages/ara.m3u",
    "https://iptv-org.github.io/iptv/languages/fra.m3u",
   ]

output_file = "combined.m3u"
MAX_WORKERS = 10  # Reduced for GitHub Actions
REQUEST_TIMEOUT = 8
REQUEST_DELAY = 0.1

# Session for connection pooling
session = requests.Session()
session.headers.update({
    'User-Agent': 'Mozilla/5.0 (compatible; IPTV-Checker/1.0)',
})

def check_url(url):
    """Check if a stream URL is accessible."""
    time.sleep(REQUEST_DELAY)  # Rate limiting
    
    try:
        # Try HEAD first (faster)
        response = session.head(
            url, 
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True
        )
        
        if response.status_code == 405:  # HEAD not allowed
            # Fall back to GET
            response = session.get(
                url,
                timeout=REQUEST_TIMEOUT,
                stream=True,
                allow_redirects=True
            )
            response.close()
        
        return 200 <= response.status_code < 400
        
    except requests.exceptions.Timeout:
        logger.debug(f"Timeout: {url}")
        return False
    except requests.exceptions.ConnectionError:
        logger.debug(f"Connection Error: {url}")
        return False
    except Exception as e:
        logger.debug(f"Error: {url} - {type(e).__name__}")
        return False

def parse_m3u(content, source):
    """Parse M3U content and extract streams."""
    streams = []
    lines = content.strip().splitlines()
    
    if not lines:
        logger.warning(f"Empty response from {source}")
        return streams
    
    if not lines[0].startswith('#EXTM3U'):
        logger.warning(f"Not a valid M3U from {source}")
        return streams
    
    for i in range(len(lines) - 1):
        if lines[i].startswith('#EXTINF'):
            url = lines[i + 1].strip()
            if url and not url.startswith('#'):
                streams.append((lines[i], url))
    
    return streams

def fetch_source(url):
    """Fetch streams from a source URL."""
    try:
        logger.info(f"📥 Fetching: {url}")
        response = session.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return parse_m3u(response.text, url)
    except Exception as e:
        logger.error(f"❌ Failed to fetch {url}: {str(e)[:100]}")
        return []

def main():
    logger.info("🚀 Starting IPTV playlist combiner")
    logger.info("=" * 50)
    
    all_streams = []
    
    # 1. Fetch all sources
    for source in sources:
        streams = fetch_source(source)
        all_streams.extend(streams)
        time.sleep(0.3)  # Delay between sources
    
    # 2. Remove duplicates
    unique_streams = []
    seen_urls = set()
    
    for extinf, url in all_streams:
        if url not in seen_urls:
            seen_urls.add(url)
            unique_streams.append((extinf, url))
    
    logger.info(f"📊 Found {len(unique_streams)} unique streams")
    logger.info("=" * 50)
    logger.info("🔍 Testing stream availability...")
    
    # 3. Test streams
    live_streams = []
    dead_count = 0
    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {}
        for extinf, url in unique_streams:
            future = executor.submit(check_url, url)
            futures[future] = (extinf, url)
        
        for i, future in enumerate(as_completed(futures), 1):
            extinf, url = futures[future]
            
            if i % 100 == 0:
                logger.info(f"  Progress: {i}/{len(unique_streams)}")
            
            if future.result():
                live_streams.append((extinf, url))
            else:
                dead_count += 1
    
    # 4. Sort by channel name
    live_streams.sort(key=lambda x: x[0].lower())
    
    # 5. Write output
    with open(output_file, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        f.write(f"# Generated: {time.ctime()}\n")
        f.write(f"# Sources: {len(sources)}\n")
        f.write(f"# Live streams: {len(live_streams)}\n\n")
        
        for extinf, url in live_streams:
            f.write(f"{extinf}\n")
            f.write(f"{url}\n")
    
    # 6. Summary
    logger.info("=" * 50)
    logger.info("✅ COMPLETED")
    logger.info(f"   Total sources: {len(sources)}")
    logger.info(f"   Unique streams: {len(unique_streams)}")
    logger.info(f"   Live streams: {len(live_streams)}")
    logger.info(f"   Dead streams: {dead_count}")
    logger.info(f"   Success rate: {len(live_streams)/max(len(unique_streams),1)*100:.1f}%")
    logger.info(f"   Output file: {output_file}")
    logger.info("=" * 50)
    
    return 0

if __name__ == "__main__":
    exit(main())
