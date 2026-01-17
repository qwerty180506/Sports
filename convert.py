import subprocess
import sys
import time
import logging
import re
import json
import concurrent.futures
from urllib.parse import urljoin

# --- AUTO-INSTALLER ---
def install(package):
    subprocess.check_call([sys.executable, "-m", "pip", "install", package])

try:
    from seleniumwire import webdriver
except ImportError:
    print("[*] Installing selenium-wire...")
    install("selenium-wire")
    install("blinker==1.7.0")
    from seleniumwire import webdriver
# ----------------------

from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select
from webdriver_manager.chrome import ChromeDriverManager

# --- CONFIGURATION ---
BASE_URL = "https://timstreams.site/"
OUTPUT_FILE = "timstreams_sports.m3u"
LOG_FILE = "scraper.log"
TIMEOUT = 30
MAX_WORKERS = 2  # Run 2 browsers in parallel (Safe for GitHub Actions)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler(LOG_FILE, mode='w'), logging.StreamHandler()]
)

def create_driver():
    options = Options()
    options.add_argument("--headless") 
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    # Suppress selenium-wire logs to keep output clean
    logging.getLogger('seleniumwire').setLevel(logging.ERROR)
    
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    
    try:
        driver.execute_cdp_cmd("Debugger.disable", {})
    except: pass
        
    return driver

def get_sports_channels():
    """
    Navigates to the page, applies the Sports filter, and extracts links.
    """
    driver = create_driver()
    wait = WebDriverWait(driver, TIMEOUT)
    channels = []
    
    try:
        logging.info("[*] Navigating to TimStreams...")
        driver.get(BASE_URL)
        
        # Click 24/7 Channels
        btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//*[contains(text(), '24/7 Channels')]")))
        driver.execute_script("arguments[0].click();", btn)
        wait.until(EC.presence_of_element_located((By.CLASS_NAME, "btn-watch")))
        time.sleep(2)
        
        # Apply Sports Filter
        logging.info("[*] Applying 'Sports' Category Filter...")
        try:
            # Attempt 1: Standard Select
            select_element = driver.find_element(By.TAG_NAME, "select")
            select = Select(select_element)
            select.select_by_visible_text("Sports")
            time.sleep(3) # Wait for grid refresh
        except:
            logging.warning("[!] Filter click failed. Will filter by text content instead.")

        # Extract Visible Channels
        buttons = driver.find_elements(By.CLASS_NAME, "btn-watch")
        logging.info(f"[*] Scanning {len(buttons)} total cards for Sports content...")
        
        for btn in buttons:
            try:
                if not btn.is_displayed():
                    continue
                
                # Double Check: Look for "Sports" text in the card description
                parent = btn.find_element(By.XPATH, "./..")
                card_text = parent.text.lower()
                
                # Strict Filter: Only add if card explicitly says "Sports" or we successfully filtered earlier
                # (You can remove 'or True' to enforce strict text filtering if the dropdown fails)
                if "sports" in card_text or "espn" in card_text or "nfl" in card_text: 
                    onclick = btn.get_attribute("onclick")
                    raw_name = parent.find_element(By.TAG_NAME, "h3").text.strip().replace("24/7:", "").strip()
                    
                    match = re.search(r"['\"](.*?)['\"]", onclick)
                    if match:
                        full_url = urljoin(BASE_URL, match.group(1))
                        if not any(x['url'] == full_url for x in channels):
                            channels.append({'name': raw_name, 'url': full_url})
            except:
                continue
                
    except Exception as e:
        logging.error(f"[!] Error getting channels: {e}")
    finally:
        driver.quit()
        
    logging.info(f"[*] Found {len(channels)} valid Sports channels.")
    return channels

def process_channel(channel_info):
    """
    Worker function to process a single channel.
    """
    driver = create_driver()
    found_link = None
    
    try:
        # logging.info(f"    -> Checking: {channel_info['name']}")
        driver.get(channel_info['url'])
        
        # Handle Iframe
        time.sleep(2)
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        if iframes:
            driver.switch_to.frame(iframes[0])
            time.sleep(1)
            try:
                # Center click
                video = driver.find_element(By.TAG_NAME, "video")
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", video)
                driver.execute_script("arguments[0].click();", video)
            except: pass
        
        # SMART WAIT LOOP (The Speed Fix)
        # Instead of sleeping 8s, we check every 0.5s for up to 10s
        for _ in range(20): 
            for request in driver.requests:
                if request.response:
                    url = request.url
                    if ".m3u8" in url and "http" in url:
                        # Success! Found it early.
                        found_link = url
                        break
            if found_link:
                break
            time.sleep(0.5)
            
    except Exception as e:
        # logging.error(f"    [!] Error on {channel_info['name']}: {e}")
        pass
    finally:
        driver.quit()
        
    if found_link:
        logging.info(f"    [+] {channel_info['name']} -> Found!")
        return {'name': channel_info['name'], 'link': found_link}
    else:
        logging.warning(f"    [-] {channel_info['name']} -> No stream.")
        return None

def main():
    start_time = time.time()
    
    # 1. Get Channel List
    channels = get_sports_channels()
    
    if not channels:
        logging.error("[!] No channels found. Exiting.")
        return

    # 2. Parallel Processing
    logging.info(f"[*] Extracting streams using {MAX_WORKERS} workers...")
    valid_streams = []
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # Submit all tasks
        future_to_channel = {executor.submit(process_channel, ch): ch for ch in channels}
        
        # Process as they complete
        for future in concurrent.futures.as_completed(future_to_channel):
            result = future.result()
            if result:
                valid_streams.append(result)

    # 3. Save
    if valid_streams:
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n")
            for stream in valid_streams:
                f.write(f'#EXTINF:-1 group-title="TimStreams Sports",{stream["name"]}\n')
                f.write(f'{stream["link"]}\n')
        
        duration = time.time() - start_time
        logging.info(f"[*] DONE. Saved {len(valid_streams)} streams in {duration:.2f} seconds.")
    else:
        logging.warning("[!] No streams found.")

if __name__ == "__main__":
    main()
