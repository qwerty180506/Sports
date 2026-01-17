import subprocess
import sys
import time
import logging
import re
import json
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
OUTPUT_FILE = "timstreams_sports.m3u"  # Renamed for clarity
LOG_FILE = "scraper.log"
TIMEOUT = 45

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
    
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    
    # Disable Debugger to prevent freezing
    try:
        driver.execute_cdp_cmd("Debugger.disable", {})
    except: pass
        
    return driver

def main():
    driver = None
    valid_streams = []
    
    try:
        logging.info("[*] Starting Scraper v27.0 (Sports Filter Mode)...")
        driver = setup_driver()
        wait = WebDriverWait(driver, TIMEOUT)
        
        # --- 1. NAVIGATE & FILTER ---
        logging.info("[*] Navigating to 24/7 Channels...")
        driver.get(BASE_URL)
        
        try:
            # Click Menu
            btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//*[contains(text(), '24/7 Channels')]")))
            driver.execute_script("arguments[0].click();", btn)
            wait.until(EC.presence_of_element_located((By.CLASS_NAME, "btn-watch")))
            time.sleep(2)
            
            # --- NEW: APPLY SPORTS FILTER ---
            logging.info("[*] Applying 'Sports' filter...")
            try:
                # Locate the dropdown (usually a <select> tag)
                # We look for the select element that contains the 'Sports' option
                select_element = driver.find_element(By.XPATH, "//select[.//option[contains(text(), 'Sports')]]")
                
                # Select "Sports"
                select = Select(select_element)
                select.select_by_visible_text("Sports")
                
                logging.info("    [+] Selected 'Sports'. Waiting for grid to update...")
                time.sleep(3) # Wait for the grid to refresh
                
            except Exception as e:
                # Fallback: Try clicking anything that looks like a dropdown item named Sports
                logging.warning(f"    [!] Standard select failed ({e}). Trying fallback click...")
                try:
                    option = driver.find_element(By.XPATH, "//*[contains(text(), 'Sports')]")
                    driver.execute_script("arguments[0].click();", option)
                    time.sleep(3)
                except:
                    logging.error("    [!] Could not apply filter. Proceeding with all channels.")

        except Exception as e:
            logging.critical("[!] Navigation/Filter failed.")
            raise e
            
        # --- 2. EXTRACT VISIBLE CHANNELS ---
        buttons = driver.find_elements(By.CLASS_NAME, "btn-watch")
        channels = []
        
        for btn in buttons:
            try:
                # CRITICAL: Only get channels that are VISIBLE (not hidden by filter)
                if not btn.is_displayed():
                    continue
                    
                onclick = btn.get_attribute("onclick")
                # Get the name from the card
                raw_name = btn.find_element(By.XPATH, "./../h3").text.strip().replace("24/7:", "").strip()
                
                match = re.search(r"['\"](.*?)['\"]", onclick)
                if match:
                    full_url = urljoin(BASE_URL, match.group(1))
                    if not any(x['url'] == full_url for x in channels):
                        channels.append({'name': raw_name, 'url': full_url})
            except:
                continue
        
        logging.info(f"[*] Found {len(channels)} Sports channels.")

        # --- 3. EXTRACTION LOOP (Same as v26) ---
        for i, ch in enumerate(channels):
            logging.info(f"[{i+1}/{len(channels)}] Visiting: {ch['name']}")
            
            try:
                del driver.requests # Clear history
                driver.get(ch['url'])
                time.sleep(4)
                
                # Iframe Handling
                iframes = driver.find_elements(By.TAG_NAME, "iframe")
                if iframes:
                    driver.switch_to.frame(iframes[0])
                    time.sleep(1)
                    try:
                        video = driver.find_element(By.TAG_NAME, "video")
                        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", video)
                        driver.execute_script("arguments[0].click();", video)
                    except:
                        pass
                
                time.sleep(8) 
                
                found_link = None
                
                # Scan Traffic
                for request in driver.requests:
                    if request.response:
                        url = request.url
                        
                        # Catch-All m3u8 filter
                        if ".m3u8" in url and "http" in url:
                            found_link = url
                            if "master" in url or "index" in url:
                                break
                
                if found_link:
                    logging.info(f"    [+] SUCCESS: {found_link[:60]}...")
                    valid_streams.append({'name': ch['name'], 'link': found_link})
                else:
                    logging.warning("    [-] No stream found.")
                    
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
                    f.write(f'#EXTINF:-1 group-title="TimStreams Sports",{stream["name"]}\n')
                    f.write(f'{stream["link"]}\n')
            logging.info(f"[*] DONE. Saved {len(valid_streams)} streams.")

if __name__ == "__main__":
    main()
