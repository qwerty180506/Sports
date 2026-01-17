import time
import json
import logging
import re
from urllib.parse import urljoin, unquote
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# --- CONFIGURATION ---
BASE_URL = "https://timstreams.site/"
OUTPUT_FILE = "timstreams_v19.m3u"
LOG_FILE = "scraper.log"
TIMEOUT = 30

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler(LOG_FILE, mode='w'), logging.StreamHandler()]
)

def setup_driver():
    options = Options()
    options.add_argument("--headless") 
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    
    # CRITICAL: Allow Autoplay in Headless Mode
    options.add_argument("--autoplay-policy=no-user-gesture-required")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=options)

def extract_from_source(driver):
    """
    Scans the raw HTML/JS for .m3u8 links using Regex.
    Returns the first valid link found, or None.
    """
    try:
        source = driver.page_source
        # Regex for m3u8 URLs (Standard & Encoded)
        patterns = [
            r'(https?://[^\s"\'<>]+?\.m3u8[^\s"\'<>]*)',  # Standard
            r'(https?%3A%2F%2F[^\s"\'<>]+?\.m3u8)',      # URL Encoded
            r'file:\s*["\'](https?://.*?)["\']',         # JWPlayer syntax
            r'source:\s*["\'](https?://.*?)["\']'        # Clappr syntax
        ]
        
        for p in patterns:
            matches = re.findall(p, source)
            for match in matches:
                # Clean up match
                clean = match.strip('",\'')
                if "%3A" in clean:
                    clean = unquote(clean)
                
                # Validation
                if ".m3u8" in clean and "http" in clean:
                    logging.info(f"    [+] Regex found link: {clean[:40]}...")
                    return clean
    except:
        pass
    return None

def force_play_and_sniff(driver):
    """
    Attempts to play the video and sniff network traffic.
    """
    # 1. Try generic click
    try:
        video_el = driver.find_element(By.TAG_NAME, "video")
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", video_el)
        driver.execute_script("arguments[0].play();", video_el)
    except:
        # Click overlay if video tag missing
        try:
            overlay = driver.find_element(By.CSS_SELECTOR, "div[class*='play'], button[class*='play']")
            driver.execute_script("arguments[0].click();", overlay)
        except:
            pass

    time.sleep(8) # Wait for buffer

    # 2. Sniff
    logs = driver.get_log("performance")
    for entry in logs:
        try:
            message = json.loads(entry["message"])["message"]
            if message["method"] == "Network.requestWillBeSent":
                url = message["params"]["request"]["url"]
                if ".m3u8" in url and "http" in url:
                    return url
        except:
            continue
    return None

def main():
    driver = None
    valid_streams = []
    
    try:
        logging.info("[*] Starting Scraper v19.0 (Hybrid Mode)...")
        driver = setup_driver()
        wait = WebDriverWait(driver, TIMEOUT)
        
        # --- 1. EXTRACT CHANNELS ---
        driver.get(BASE_URL)
        logging.info("[*] Extracting channels...")
        try:
            btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//*[contains(text(), '24/7 Channels')]")))
            driver.execute_script("arguments[0].click();", btn)
            wait.until(EC.presence_of_element_located((By.CLASS_NAME, "btn-watch")))
            time.sleep(2)
        except Exception as e:
            logging.critical("[!] Menu navigation failed.")
            raise e
            
        buttons = driver.find_elements(By.CLASS_NAME, "btn-watch")
        channels = []
        for btn in buttons:
            try:
                onclick = btn.get_attribute("onclick")
                raw_name = btn.find_element(By.XPATH, "./../h3").text.strip().replace("24/7:", "").strip()
                match = re.search(r"['\"](.*?)['\"]", onclick)
                if match:
                    full_url = urljoin(BASE_URL, match.group(1))
                    if not any(x['url'] == full_url for x in channels):
                        channels.append({'name': raw_name, 'url': full_url})
            except:
                continue
        
        logging.info(f"[*] Found {len(channels)} channels.")

        # --- 2. PROCESSING LOOP ---
        for i, ch in enumerate(channels):
            logging.info(f"[{i+1}/{len(channels)}] Visiting: {ch['name']}")
            
            try:
                driver.get(ch['url'])
                time.sleep(2) # Load page
                
                # Check for iframes
                iframes = driver.find_elements(By.TAG_NAME, "iframe")
                found_link = None
                
                # STRATEGY A: Regex on Main Page
                found_link = extract_from_source(driver)
                
                # STRATEGY B: Switch to Iframe & Regex/Sniff
                if not found_link and iframes:
                    driver.switch_to.frame(iframes[0])
                    time.sleep(1)
                    
                    # Try Regex inside iframe
                    found_link = extract_from_source(driver)
                    
                    # If regex failed, try Network Sniffing
                    if not found_link:
                        found_link = force_play_and_sniff(driver)
                        
                    driver.switch_to.default_content()
                
                # STRATEGY C: Network Sniff on Main Page (if no iframe or failed)
                if not found_link and not iframes:
                    found_link = force_play_and_sniff(driver)

                # --- SAVE RESULT ---
                if found_link:
                    logging.info(f"    [+] SUCCESS: {found_link[:60]}...")
                    valid_streams.append({'name': ch['name'], 'link': found_link})
                else:
                    logging.warning("    [-] Failed to extract.")

            except Exception as e:
                logging.error(f"    [!] Error: {e}")
                driver.switch_to.default_content()

    except Exception as e:
        logging.critical(f"Global Crash: {e}")
    
    finally:
        if driver:
            driver.quit()
        
        if valid_streams:
            with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
                f.write("#EXTM3U\n")
                for stream in valid_streams:
                    f.write(f'#EXTINF:-1 group-title="TimStreams",{stream["name"]}\n')
                    f.write(f'{stream["link"]}\n')
            logging.info(f"[*] DONE. Saved {len(valid_streams)} streams.")

if __name__ == "__main__":
    main()
