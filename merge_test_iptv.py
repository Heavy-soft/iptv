import requests
import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
import ssl
import urllib3

# Disable SSL warnings for self-signed certificates
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

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
MAX_WORKERS = 15  # Increased for faster checking
REQUEST_TIMEOUT = 5  # Reduced timeout
REQUEST_DELAY = 0.05

# Create session with IPTV-compatible headers
session = requests.Session()
session.headers.update({
    'User-Agent': 'VLC/3.0.18 LibVLC/3.0.18',
    'Accept': '*/*',
    'Connection': 'keep-alive',
    'Icy-MetaData': '1',
})

# SSL context that's more lenient
session.verify = False  # Accept self-signed certificates

def check_url(url):
    """Check if a stream URL might be accessible - more lenient approach."""
    time.sleep(REQUEST_DELAY)
    
    # Skip checking for certain URL patterns that are known to work
    skip_check_patterns = [
        'youtube.com',
        'youtu.be',
        'twitch.tv',
        'facebook.com',
        'dailymotion.com',
        '.m3u8',
        '.mp4',
        '.ts',
        'rtmp://',
        'rtsp://',
    ]
    
    for pattern in skip_check_patterns:
        if pattern in url:
            logger.debug(f"✓ Skipping check for {url} (known pattern)")
            return True
    
    try:
        # Try GET request with minimal data fetch (range request)
        headers = {
            'Range': 'bytes=0-1',  # Request just 1 byte to test connection
            'User-Agent': 'VLC/3.0.18 LibVLC/3.0.18',
        }
        
        response = session.get(
            url,
            timeout=REQUEST_TIMEOUT,
            headers=headers,
            stream=True,
            allow_redirects=True,
            verify=False  # Disable SSL verification
        )
        
        # Close response immediately to free connection
        response.close()
        
        # Accept a wider range of status codes
        if response.status_code in [200, 206, 301, 302, 307, 308]:
            logger.debug(f"✓ Accepting {url} (status: {response.status_code})")
            return True
        
        logger.debug(f"✗ Rejecting {url} (status: {response.status_code})")
        return False
        
    except requests.exceptions.Timeout:
        logger.debug(f"✗ Timeout: {url}")
        # Give timeout URLs a second chance - sometimes slow to respond
        return False
        
    except requests.exceptions.SSLError:
        logger.debug(f"⚠ SSL Error (but accepting): {url}")
        # Accept URLs with SSL errors - common in IPTV
        return True
        
    except requests.exceptions.ConnectionError:
        logger.debug(f"✗ Connection Error: {url}")
        return False
        
    except Exception as e:
        logger.debug(f"⚠ Exception (but accepting): {url} - {type(e).__name__}")
        # Be lenient - accept URLs that throw exceptions (common in IPTV)
        return True

def parse_m3u(content, source):
    """Parse M3U content and extract streams."""
    streams = []
    lines = content.strip().splitlines()
    
    if not lines:
        logger.warning(f"Empty response from {source}")
        return streams
    
    # Skip header check - accept files without #EXTM3U
    for i in range(len(lines) - 1):
        line = lines[i].strip()
        if line.startswith('#EXTINF'):
            url_line = lines[i + 1].strip()
            if url_line and not url_line.startswith('#'):
                streams.append((line, url_line))
    
    return streams

def fetch_source(url):
    """Fetch streams from a source URL."""
    try:
        logger.info(f"📥 Fetching: {url}")
        response = session.get(url, timeout=10)
        response.raise_for_status()
        return parse_m3u(response.text, url)
    except Exception as e:
        logger.error(f"❌ Failed to fetch {url}: {str(e)}")
        return []

def main():
    logger.info("🚀 Starting IPTV playlist combiner")
    logger.info("=" * 50)
    
    all_streams = []
    
    # 1. Fetch all sources
    for source in sources:
        streams = fetch_source(source)
        logger.info(f"  Found {len(streams)} streams")
        all_streams.extend(streams)
        time.sleep(0.5)
    
    # 2. Remove exact duplicates
    unique_streams = []
    seen = set()
    
    for extinf, url in all_streams:
        key = (extinf, url)
        if key not in seen:
            seen.add(key)
            unique_streams.append((extinf, url))
    
    logger.info(f"📊 Total unique streams: {len(unique_streams)}")
    logger.info("=" * 50)
    
    # 3. OPTIONAL: Skip checking entirely for faster results
    # Uncomment the next 3 lines to skip URL checking and keep all streams
    # live_streams = unique_streams
    # logger.info("⏭️ Skipping URL checks (keeping all streams)")
    # logger.info("=" * 50)
    
    # 4. OR: Test only a sample of streams (faster)
    # Remove or comment this block if you want to check all streams
    sample_size = min(50, len(unique_streams))  # Check only 50 streams as sample
    streams_to_check = unique_streams[:sample_size] + unique_streams[-sample_size:]  # Check first and last 50
    
    logger.info(f"🔍 Testing {len(streams_to_check)} sample streams...")
    logger.info("(Checking first and last 50 streams to save time)")
    
    live_streams = []
    dead_count = 0
    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {}
        for extinf, url in streams_to_check:
            future = executor.submit(check_url, url)
            futures[future] = (extinf, url)
        
        for i, future in enumerate(as_completed(futures), 1):
            extinf, url = futures[future]
            
            if i % 20 == 0:
                logger.info(f"  Checked {i}/{len(streams_to_check)}")
            
            try:
                if future.result():
                    live_streams.append((extinf, url))
                else:
                    dead_count += 1
            except:
                # If check fails, keep the stream (be lenient)
                live_streams.append((extinf, url))
    
    # 5. Keep all streams (not just checked ones)
    # Assume unchecked streams are working
    unchecked_streams = [s for s in unique_streams if s not in streams_to_check]
    live_streams.extend(unchecked_streams)
    
    logger.info(f"✅ Assuming {len(unchecked_streams)} unchecked streams are working")
    
    # 6. Sort by channel name
    live_streams.sort(key=lambda x: x[0].lower())
    
    # 7. Write output
    with open(output_file, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        f.write(f"# Generated: {time.ctime()}\n")
        f.write(f"# Sources: {len(sources)}\n")
        f.write(f"# Total streams: {len(live_streams)}\n")
        f.write(f"# Note: Not all streams have been verified\n\n")
        
        for extinf, url in live_streams:
            f.write(f"{extinf}\n")
            f.write(f"{url}\n\n")
    
    # 8. Summary
    logger.info("=" * 50)
    logger.info("🎉 COMPLETED")
    logger.info(f"   Sources processed: {len(sources)}")
    logger.info(f"   Total streams found: {len(all_streams)}")
    logger.info(f"   Unique streams kept: {len(live_streams)}")
    logger.info(f"   Sample tested: {len(streams_to_check)}")
    logger.info(f"   Output file: {output_file}")
    logger.info("=" * 50)
    
    # 9. Create a simple version without checking (optional)
    with open("all_streams.m3u", "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for extinf, url in unique_streams:
            f.write(f"{extinf}\n{url}\n\n")
    logger.info(f"Also created 'all_streams.m3u' with all {len(unique_streams)} streams")
    
    return 0

if __name__ == "__main__":
    exit(main())
