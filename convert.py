import time
import json
import concurrent.futures
from urllib.parse import urljoin
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# --- CONFIGURATION ---
BASE_URL = "https://timstreams.site/"
OUTPUT_FILE = "timstreams_v9.m3u"
MAX_WORKERS = 1  # Keep 1 for network reliability
TIMEOUT = 30

def setup_driver():
    """Creates a Chrome instance with Network Logging enabled."""
    chrome_options = Options()
    chrome_options.add_argument("--headless") 
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    # Enable Performance Logging
    chrome_options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=chrome_options)

def get_channels():
    print(f"[*] Navigating to {BASE_URL}...")
    driver = setup_driver()
    links_found = []
    
    try:
        driver.get(BASE_URL)
        wait = WebDriverWait(driver, TIMEOUT)
        
        # --- STEP 1: FORCE NAVIGATION ---
        print("[*] Finding '24/7 Channels' button...")
        
        # Try finding visible buttons first
        buttons = driver.find_elements(By.XPATH, "//*[contains(text(), '24/7 Channels')]")
        clicked = False
        
        for btn in buttons:
            if btn.is_displayed():
                driver.execute_script("arguments[0].scrollIntoView(true);", btn)
                time.sleep(1)
                driver.execute_script("arguments[0].click();", btn)
                clicked = True
                break
        
        if not clicked and buttons:
            print("    - Force-clicking hidden button...")
            driver.execute_script("arguments[0].click();", buttons[0])

        # --- STEP 2: VERIFY PAGE LOAD ---
        print("[*] Waiting for content...")
        try:
            # Wait for search bar (Confirmed from your logs this works)
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input[placeholder*='Search']")))
            print("[+] Page Loaded Successfully.")
        except:
            print("[!] Navigation check timed out (Script might still work)...")

        # --- STEP 3: SCRAPE CHANNELS (LOOSE FILTER) ---
        print("[*] Scraping all links...")
        time.sleep(5) # Wait for JS to populate grid
        
        elements = driver.find_elements(By.TAG_NAME, "a")
        
        # System links to ignore
        blocklist = ['donate', 'login', 'register', 'discord', 'policy', 'multiview', 'upcoming', 'replay', 'dmca', 'home']
        
        for elem in elements:
            try:
                href = elem.get_attribute("href")
                text = elem.text.strip()
                
                # Get inner text if standard text is empty (sometimes hidden in spans)
                if not text:
                    text = elem.get_attribute("innerText").strip()

                # Basic validation
                if not href or "javascript" in href:
                    continue
                    
                # Fix relative links (e.g. /watch/bluey -> https://timstreams.site/watch/bluey)
                full_url = urljoin(BASE_URL, href)
                
                # Apply Blocklist
                if any(bad in full_url.lower() for bad in blocklist) or any(bad in text.lower() for bad in blocklist):
                    continue

                # If it looks vaguely like a content link
                # We assume anything remaining is a channel
                if full_url != BASE_URL:
                    # Name fallback
                    name = text if text else full_url.split("/")[-1].replace("-", " ").title()
                    
                    if not any(d['url'] == full_url for d in links_found):
                        links_found.append({'name': name, 'url': full_url})
            except:
                continue

        # --- DEBUG: DUMP HTML IF EMPTY ---
        if len(links_found) == 0:
            print("[!] 0 Channels found. Dumping HTML for debugging...")
            with open("debug_source.html", "w", encoding="utf-8") as f:
                f.write(driver.page_source)

    except Exception as e:
        print(f"[!] Error: {e}")
    finally:
        driver.quit()
        
    print(f"[*] Found {len(links_found)} potential channels.")
    return links_found

def sniff_stream(channel_info):
    driver = setup_driver()
    stream_url = None
    
    try:
        print(f"    Scanning: {channel_info['name']}...")
        driver.get(channel_info['url'])
        time.sleep(6) # Wait for player
        
        # 1. Network Sniffing
        logs = driver.get_log("performance")
        for entry in logs:
            message = json.loads(entry["message"])["message"]
            if message["method"] == "Network.requestWillBeSent":
                url = message["params"]["request"]["url"]
                if ".m3u8" in url and "http" in url:
                    stream_url = url
                    if "token" in url: # Prefer tokenized links
                        break
        
        # 2. Iframe Fallback
        if not stream_url:
            iframes = driver.find_elements(By.TAG_NAME, "iframe")
            for frame in iframes:
                src = frame.get_attribute("src")
                if src and ".m3u8" in src:
                    stream_url = src
                    break

    except Exception:
        pass
    finally:
        driver.quit()
        
    if stream_url:
        print(f"    [+] FOUND: {stream_url[:50]}...")
        return {'name': channel_info['name'], 'link': stream_url}
    else:
        print(f"    [-] No stream found.")
        return None

def main():
    channels = get_channels()
    
    if not channels:
        print("[!] No channels found. Please upload 'debug_source.html' to the chat.")
        return

    valid_streams = []
    print(f"[*] Sniffing streams from {len(channels)} channels...")
    
    # Limit to first 3 channels for testing speed (Remove [:3] to run all)
    for channel in channels: 
        result = sniff_stream(channel)
        if result:
            valid_streams.append(result)

    if valid_streams:
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n")
            for stream in valid_streams:
                clean_name = stream["name"].replace("24/7:", "").strip()
                f.write(f'#EXTINF:-1 group-title="TimStreams",{clean_name}\n')
                f.write(f'{stream["link"]}\n')
        print(f"[*] Saved {len(valid_streams)} streams.")
    else:
        print("[!] No streams found.")

if __name__ == "__main__":
    main()
