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
OUTPUT_FILE = "timstreams_v20.m3u"
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
    
    # Enable Autoplay
    options.add_argument("--autoplay-policy=no-user-gesture-required")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=options)

def inject_play_commands(driver):
    """
    Directly commands the video player engine to start.
    """
    # 1. Try Standard HTML5 Video
    try:
        driver.execute_script("""
            var v = document.querySelector('video');
            if(v) { v.muted = true; v.play(); console.log('HTML5 Play sent'); }
        """)
    except: pass

    # 2. Try Clappr (Common on streaming sites)
    try:
        driver.execute_script("""
            if(typeof Clappr !== 'undefined' && Clappr.players.length > 0) {
                Clappr.players[0].mute();
                Clappr.players[0].play();
                console.log('Clappr Play sent');
            }
        """)
    except: pass

    # 3. Try JWPlayer
    try:
        driver.execute_script("""
            if(typeof jwplayer === 'function') {
                jwplayer().setMute(true);
                jwplayer().play();
                console.log('JWPlayer Play sent');
            }
        """)
    except: pass

def check_logs_for_m3u8(driver):
    """
    Scans network logs for m3u8.
    """
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
        logging.info("[*] Starting Scraper v20.0 (API Injector)...")
        driver = setup_driver()
        wait = WebDriverWait(driver, TIMEOUT)
        
        # --- 1. EXTRACT CHANNELS ---
        driver.get(BASE_URL)
        logging.info("[*] Extracting channels...")
        try:
            # Menu Navigation
            btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//*[contains(text(), '24/7 Channels')]")))
            driver.execute_script("arguments[0].click();", btn)
            wait.until(EC.presence_of_element_located((By.CLASS_NAME, "btn-watch")))
            time.sleep(2)
            
            # Button Scraping
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

        except Exception as e:
            logging.critical("[!] Menu navigation failed.")
            raise e

        # --- 2. VISIT & INJECT ---
        for i, ch in enumerate(channels):
            logging.info(f"[{i+1}/{len(channels)}] Visiting: {ch['name']}")
            
            try:
                driver.get(ch['url'])
                time.sleep(3) # Initial load
                
                found_link = None
                
                # --- PHASE A: Main Page Injection ---
                inject_play_commands(driver)
                time.sleep(2)
                found_link = check_logs_for_m3u8(driver)
                
                # --- PHASE B: Recursive Iframe Injection ---
                if not found_link:
                    iframes = driver.find_elements(By.TAG_NAME, "iframe")
                    if iframes:
                        logging.info(f"    [i] Found {len(iframes)} iframes. Diving in...")
                        
                        for frame in iframes:
                            try:
                                driver.switch_to.frame(frame)
                                inject_play_commands(driver)
                                time.sleep(2) # Give it a moment to request
                                
                                # Check logs (Logs are global, no need to switch back to check)
                                found_link = check_logs_for_m3u8(driver)
                                if found_link:
                                    break
                                    
                                driver.switch_to.default_content()
                            except:
                                driver.switch_to.default_content()
                
                # --- PHASE C: Center Click (Backup) ---
                if not found_link:
                    driver.switch_to.default_content()
                    try:
                        # Click dead center of screen to hit any overlay
                        actions = ActionChains(driver)
                        actions.move_by_offset(960, 540).click().perform() # 1920x1080 center
                        logging.info("    [+] Center-screen click attempted.")
                        time.sleep(4)
                        found_link = check_logs_for_m3u8(driver)
                    except: pass

                # --- RESULT ---
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
