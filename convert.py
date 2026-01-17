import subprocess
import sys
import time
import logging
import re
import os
from urllib.parse import urljoin

# --- AUTO-INSTALLER (Fixes ModuleNotFoundError) ---
def install(package):
    subprocess.check_call([sys.executable, "-m", "pip", "install", package])

try:
    from seleniumwire import webdriver
except ImportError:
    print("[*] Installing missing libraries (selenium-wire)...")
    install("selenium-wire")
    install("blinker==1.7.0") # Critical fix for selenium-wire
    from seleniumwire import webdriver
# --------------------------------------------------

from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# --- CONFIGURATION ---
BASE_URL = "https://timstreams.site/"
OUTPUT_FILE = "timstreams_wire.m3u"
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
    
    service = Service(ChromeDriverManager().install())
    
    # Initialize Selenium-Wire driver
    driver = webdriver.Chrome(service=service, options=options)
    return driver

def main():
    driver = None
    valid_streams = []
    
    try:
        logging.info("[*] Starting Scraper v23.0 (Self-Installing)...")
        driver = setup_driver()
        wait = WebDriverWait(driver, TIMEOUT)
        
        # --- 1. EXTRACT CHANNELS ---
        logging.info("[*] Extracting channel list...")
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
                raw_name = parent.find_element(By.TAG_NAME, "h3").text.strip().replace("24/7:", "").strip()
                match = re.search(r"['\"](.*?)['\"]", onclick)
                if match:
                    full_url = urljoin(BASE_URL, match.group(1))
                    if not any(x['url'] == full_url for x in channels):
                        channels.append({'name': raw_name, 'url': full_url})
            except:
                continue
        
        logging.info(f"[*] Found {len(channels)} channels.")

        # --- 2. SNIFFING LOOP ---
        for i, ch in enumerate(channels):
            logging.info(f"[{i+1}/{len(channels)}] Visiting: {ch['name']}")
            
            try:
                # Clear previous requests so we don't mix up channels
                del driver.requests
                
                driver.get(ch['url'])
                time.sleep(2)
                
                # Iframe Handling
                iframes = driver.find_elements(By.TAG_NAME, "iframe")
                if iframes:
                    driver.switch_to.frame(iframes[0])
                    time.sleep(1)
                
                # Try to Play (Center Click)
                try:
                    video = driver.find_element(By.TAG_NAME, "video")
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", video)
                    driver.execute_script("arguments[0].play();", video)
                except:
                    pass
                
                # Wait for traffic
                time.sleep(8)
                
                # --- TRAFFIC ANALYSIS (THE WIRE) ---
                found_link = None
                
                # Iterate through captured requests
                for request in driver.requests:
                    if request.response:
                        url = request.url
                        
                        # 1. Check for specific Keywords (railway app from screenshot)
                        if "railway.app" in url and ".m3u8" in url:
                            found_link = url
                            break
                        
                        # 2. Check for generic m3u8
                        if ".m3u8" in url:
                            found_link = url
                            if "master" in url or "playlist" in url:
                                break
                
                if found_link:
                    logging.info(f"    [+] SUCCESS: {found_link[:80]}...")
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
                    f.write(f'#EXTINF:-1 group-title="TimStreams",{stream["name"]}\n')
                    f.write(f'{stream["link"]}\n')
            logging.info(f"[*] DONE. Saved {len(valid_streams)} streams.")

if __name__ == "__main__":
    main()
