import time
import json
import logging
import re
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
OUTPUT_FILE = "timstreams_v15.m3u"
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
    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=options)

def main():
    driver = None
    valid_streams = []
    
    try:
        logging.info("[*] Starting Scraper v15.0 (Direct Link Extractor)...")
        driver = setup_driver()
        wait = WebDriverWait(driver, TIMEOUT)
        
        # --- 1. NAVIGATE TO 24/7 PAGE ---
        logging.info("[*] Navigating to homepage...")
        driver.get(BASE_URL)
        
        logging.info("[*] Entering '24/7 Channels'...")
        try:
            # We use the text to find the menu button
            btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//*[contains(text(), '24/7 Channels')]")))
            driver.execute_script("arguments[0].click();", btn)
        except Exception as e:
            logging.critical("[!] Menu button failed.")
            raise e

        # --- 2. WAIT FOR GRID & BUTTONS ---
        logging.info("[*] Waiting for 'Tune In' buttons...")
        try:
            # Based on your image, we look for buttons with class 'btn-watch'
            wait.until(EC.presence_of_element_located((By.CLASS_NAME, "btn-watch")))
            time.sleep(5) 
        except:
            logging.critical("[!] Grid timeout.")
            raise Exception("Grid load failed")

        # --- 3. EXTRACT TARGET URLS (No Clicking!) ---
        # Instead of clicking, we read the 'onclick' attribute directly.
        # Format: onclick="location.href='watch.html?id=247-bluey'"
        buttons = driver.find_elements(By.CLASS_NAME, "btn-watch")
        logging.info(f"[*] Found {len(buttons)} 'Tune In' buttons.")
        
        channels_to_visit = []
        
        for btn in buttons:
            try:
                # 1. Get the onclick text
                onclick_text = btn.get_attribute("onclick")
                
                # 2. Get the Name (from the sibling h3 tag)
                # Structure: div > h3 (Title) ... button (Tune In)
                parent_card = btn.find_element(By.XPATH, "./..")
                raw_name = parent_card.find_element(By.TAG_NAME, "h3").text.strip()
                clean_name = raw_name.replace("24/7:", "").strip()
                
                # 3. Extract the URL using Regex
                # Looks for: 'something.html' or "something.html"
                match = re.search(r"['\"](.*?)['\"]", onclick_text)
                if match:
                    relative_url = match.group(1)
                    full_url = urljoin(BASE_URL, relative_url)
                    
                    # Avoid duplicates
                    if not any(x['url'] == full_url for x in channels_to_visit):
                         channels_to_visit.append({'name': clean_name, 'url': full_url})
            except Exception as e:
                continue

        logging.info(f"[*] Extracted {len(channels_to_visit)} valid channel URLs.")

        # --- 4. VISIT & SNIFF LOOP ---
        for i, channel in enumerate(channels_to_visit):
            logging.info(f"[{i+1}/{len(channels_to_visit)}] Visiting: {channel['name']}")
            
            try:
                # Direct Navigation (Fast & Reliable)
                driver.get(channel['url'])
                
                # Wait for player
                time.sleep(2)
                
                # Attempt Auto-Play
                try:
                    driver.execute_script("document.getElementsByTagName('video')[0].play()")
                except:
                    pass

                time.sleep(6) # Sniffing Window
                
                # Sniff Network Logs
                found_link = None
                logs = driver.get_log("performance")
                for entry in logs:
                    try:
                        message = json.loads(entry["message"])["message"]
                        if message["method"] == "Network.requestWillBeSent":
                            url = message["params"]["request"]["url"]
                            # Look for m3u8
                            if ".m3u8" in url and "http" in url:
                                found_link = url
                                if "token" in url: break
                    except:
                        continue
                
                if found_link:
                    logging.info("    [+] Stream Found!")
                    valid_streams.append({'name': channel['name'], 'link': found_link})
                else:
                    logging.warning("    [-] No M3U8 captured.")

            except Exception as e:
                logging.error(f"    [!] Error: {e}")

    except Exception as e:
        logging.critical(f"Global Crash: {e}")
    
    finally:
        if driver:
            driver.quit()
        
        # Save M3U
        if valid_streams:
            with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
                f.write("#EXTM3U\n")
                for stream in valid_streams:
                    f.write(f'#EXTINF:-1 group-title="TimStreams",{stream["name"]}\n')
                    f.write(f'{stream["link"]}\n')
            logging.info(f"[*] SUCCESS: Saved {len(valid_streams)} streams.")
        else:
            logging.warning("[!] No streams found.")

if __name__ == "__main__":
    main()
