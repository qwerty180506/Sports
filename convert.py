import time
import json
import logging
import re
from urllib.parse import urljoin
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
OUTPUT_FILE = "timstreams_v18.m3u"
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
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    # CRITICAL: Capture ALL network performance logs
    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=options)

def force_start_video(driver):
    """
    Clicks the center of the video player to trigger playback.
    """
    try:
        # 1. Find the video element
        video_el = driver.find_element(By.TAG_NAME, "video")
        
        # 2. Scroll to it
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", video_el)
        time.sleep(1)
        
        # 3. Click the center of the video (ActionChains)
        actions = ActionChains(driver)
        actions.move_to_element(video_el).click().perform()
        logging.info("    [+] Clicked center of video player.")
        
        # 4. Backup: JS Play
        driver.execute_script("arguments[0].play();", video_el)
        
    except Exception:
        # If no video tag, try clicking the generic 'player' div
        try:
            player_div = driver.find_element(By.ID, "player") # Common ID
            actions = ActionChains(driver)
            actions.move_to_element(player_div).click().perform()
            logging.info("    [+] Clicked #player div.")
        except:
            logging.info("    [!] Could not find video element to click.")

def main():
    driver = None
    valid_streams = []
    
    try:
        logging.info("[*] Starting Scraper v18.0 (Extension Mimic)...")
        driver = setup_driver()
        wait = WebDriverWait(driver, TIMEOUT)
        
        # --- 1. EXTRACT CHANNELS (Using Direct Link method) ---
        logging.info("[*] Extracting channels...")
        driver.get(BASE_URL)
        
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
                parent = btn.find_element(By.XPATH, "./..")
                name = parent.find_element(By.TAG_NAME, "h3").text.strip().replace("24/7:", "").strip()
                match = re.search(r"['\"](.*?)['\"]", onclick)
                if match:
                    full_url = urljoin(BASE_URL, match.group(1))
                    if not any(x['url'] == full_url for x in channels):
                        channels.append({'name': name, 'url': full_url})
            except:
                continue
        
        logging.info(f"[*] Processing {len(channels)} channels...")

        # --- 2. SNIFF LOOP ---
        for i, ch in enumerate(channels):
            logging.info(f"[{i+1}/{len(channels)}] Visiting: {ch['name']}")
            
            try:
                driver.get(ch['url'])
                time.sleep(2)
                
                # Iframe handling
                iframes = driver.find_elements(By.TAG_NAME, "iframe")
                if iframes:
                    driver.switch_to.frame(iframes[0])
                    time.sleep(1)
                
                # Force Start
                force_start_video(driver)
                
                # Wait 10s for the Signed URL to generate/request
                time.sleep(10)
                
                # --- TRAFFIC ANALYSIS ---
                found_link = None
                logs = driver.get_log("performance")
                
                # We collect ALL URLs to see if we missed it
                seen_urls = []
                
                for entry in logs:
                    try:
                        message = json.loads(entry["message"])["message"]
                        if message["method"] == "Network.requestWillBeSent":
                            url = message["params"]["request"]["url"]
                            
                            if "http" in url:
                                seen_urls.append(url)
                            
                            # EXACT MATCH for your screenshot: it contains ".m3u8"
                            if ".m3u8" in url:
                                found_link = url
                                # Break immediately on first master playlist
                                break
                    except:
                        continue
                
                if found_link:
                    logging.info(f"    [+] FOUND STREAM: {found_link[:60]}...")
                    valid_streams.append({'name': ch['name'], 'link': found_link})
                else:
                    logging.warning("    [-] No .m3u8 found.")
                    # DEBUG: Print the last 3 long URLs (likely the signed ones)
                    long_urls = [u for u in seen_urls if len(u) > 100]
                    if long_urls:
                        logging.info(f"    [DEBUG] Long URLs seen: {long_urls[-2:]}")

                driver.switch_to.default_content()

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
