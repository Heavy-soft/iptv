import requests
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse
import logging

# Setup logging for GitHub Actions
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# Sources - GitHub-based sources are reliable
sources = [
    "https://iptv-org.github.io/iptv/languages/ara.m3u",
    "https://iptv-org.github.io/iptv/languages/fra.m3u",
    "https://iptv-org.github.io/iptv/languages/eng.m3u",
    "https://iptv-org.github.io/iptv/languages/spa.m3u",
    "https://iptv-org.github.io/iptv/categories/news.m3u"
]

output_file = "combined.m3u"
# GitHub Actions runners can handle moderate parallelism
MAX_WORKERS = 15
# Conservative timeout for GitHub's network
REQUEST_TIMEOUT = 10
# Delay to avoid rate limiting
REQUEST_DELAY = 0.05

# Create a session with proper headers for GitHub Actions
session = requests.Session()
session.headers.update({
    'User-Agent': 'Mozilla/5.0 (compatible; GitHub-Actions-IPTV/1.0)',
    'Accept': '*/*',
    'Accept-Encoding': 'gzip, deflate',
})

def is_github_url(url):
    """Check if URL is from GitHub to apply different rate limiting."""
    parsed = urlparse(url)
    return 'github' in parsed.netloc or 'github.io' in parsed.netloc

def check_url(url):
    """Check if a stream URL is accessible."""
    try:
        # Add small delay to be polite
        time.sleep(REQUEST_DELAY)
        
        # Use GET instead of HEAD (some servers block HEAD)
        response = session.get(
            url, 
            timeout=REQUEST_TIMEOUT,
            stream=True,  # Stream to avoid downloading entire content
            allow_redirects=True
        )
        response.close()  # Close connection immediately
        
        # Accept 2xx and 3xx status codes
        if 200 <= response.status_code < 400:
            return True
        return False
        
    except requests.exceptions.Timeout:
        logger.debug(f"Timeout: {url}")
        return False
    except requests.exceptions.SSLError:
        logger.debug(f"SSL Error: {url}")
        return False
    except requests.exceptions.ConnectionError:
        logger.debug(f"Connection Error: {url}")
        return False
    except Exception as e:
        logger.debug(f"Error checking {url}: {type(e).__name__}")
        return False

def parse_m3u_content(content, source_url):
    """Parse M3U content and extract streams."""
    streams = []
    lines = content.strip().splitlines()
    
    if not lines or not lines[0].startswith('#EXTM3U'):
        logger.warning(f"Invalid M3U format in {source_url}")
        return streams
    
    for i in range(len(lines) - 1):
        if lines[i].startswith('#EXTINF'):
            url = lines[i + 1].strip()
            if url and not url.startswith('#'):
                streams.append((lines[i], url))
    
    return streams

def fetch_source(source_url):
    """Fetch and parse a single source."""
    try:
        logger.info(f"📥 Fetching: {source_url}")
        
        response = session.get(
            source_url, 
            timeout=REQUEST_TIMEOUT,
            headers={'Cache-Control': 'no-cache'}
        )
        response.raise_for_status()
        
        streams = parse_m3u_content(response.text, source_url)
        logger.info(f"  Found {len(streams)} streams in {source_url}")
        return streams
        
    except Exception as e:
        logger.error(f"Failed to fetch {source_url}: {e}")
        return []

def main():
    start_time = time.time()
    all_streams = []
    
    # Step 1: Fetch all sources
    logger.info("=" * 60)
    logger.info("🔄 Fetching sources...")
    logger.info("=" * 60)
    
    for source in sources:
        streams = fetch_source(source)
        all_streams.extend(streams)
        time.sleep(0.5)  # Delay between source fetches
    
    # Remove duplicates (by URL)
    logger.info("=" * 60)
    logger.info("🧹 Removing duplicates...")
    unique_streams = []
    seen_urls = set()
    
    for extinf, url in all_streams:
        if url not in seen_urls:
            seen_urls.add(url)
            unique_streams.append((extinf, url))
    
    logger.info(f"Total unique streams: {len(unique_streams)}")
    
    # Step 2: Test streams in parallel
    logger.info("=" * 60)
    logger.info("🔍 Testing stream availability...")
    logger.info("=" * 60)
    
    live_streams = []
    tested = 0
    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # Submit all checking tasks
        future_to_stream = {}
        for extinf, url in unique_streams:
            future = executor.submit(check_url, url)
            future_to_stream[future] = (extinf, url)
        
        # Process results as they complete
        for future in as_completed(future_to_stream):
            extinf, url = future_to_stream[future]
            tested += 1
            
            if tested % 50 == 0:
                logger.info(f"Progress: {tested}/{len(unique_streams)} streams tested")
            
            if future.result():
                live_streams.append((extinf, url))
                logger.debug(f"✓ Live: {url}")
            else:
                logger.debug(f"✗ Dead: {url}")
    
    # Step 3: Write output
    logger.info("=" * 60)
    logger.info(f"✅ Found {len(live_streams)} live streams out of {len(unique_streams)}")
    
    # Sort by channel name for better organization
    live_streams.sort(key=lambda x: x[0].lower())
    
    with open(output_file, "w", encoding="utf-8") as out:
        out.write("#EXTM3U\n")
        out.write("# Generated by GitHub Actions IPTV Combiner\n")
        out.write(f"# Total streams: {len(live_streams)}\n")
        out.write(f"# Generated at: {time.ctime()}\n\n")
        
        for extinf, url in live_streams:
            out.write(f"{extinf}\n")
            out.write(f"{url}\n\n")
    
    # Calculate statistics
    end_time = time.time()
    elapsed = end_time - start_time
    
    logger.info("=" * 60)
    logger.info("📊 Statistics:")
    logger.info(f"  Sources processed: {len(sources)}")
    logger.info(f"  Total streams found: {len(all_streams)}")
    logger.info(f"  Unique streams: {len(unique_streams)}")
    logger.info(f"  Live streams: {len(live_streams)}")
    logger.info(f"  Success rate: {(len(live_streams)/len(unique_streams)*100):.1f}%")
    logger.info(f"  Time elapsed: {elapsed:.1f} seconds")
    logger.info(f"  Output file: {output_file}")
    logger.info("=" * 60)
    
    # GitHub Actions specific: Set output if needed
    if live_streams:
        logger.info("🎉 Script completed successfully!")
        return 0
    else:
        logger.error("❌ No live streams found!")
        return 1

if __name__ == "__main__":
    exit_code = main()
    exit(exit_code)
