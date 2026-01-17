import time
import json
import logging
import traceback
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# --- CONFIGURATION ---
BASE_URL = "https://timstreams.site/"
OUTPUT_FILE = "timstreams_v12.m3u"
LOG_FILE = "scraper.log"
TIMEOUT = 30

# Setup Logging
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
    # Stealth settings
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=options)

def main():
    driver = None
    valid_streams = []
    
    try:
        logging.info(f"[*] Starting Scraper v12.0...")
        driver = setup_driver()
        wait = WebDriverWait(driver, TIMEOUT)
        
        logging.info("[*] Navigating to homepage...")
        driver.get(BASE_URL)
        
        # --- 1. NAVIGATE TO 24/7 PAGE ---
        logging.info("[*] Clicking '24/7 Channels'...")
        try:
            btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//*[contains(text(), '24/7 Channels')]")))
            driver.execute_script("arguments[0].click();", btn)
        except Exception as e:
            logging.critical("[!] Start button not found.")
            raise e

        # --- 2. WAIT FOR GRID ---
        logging.info("[*] Waiting for grid...")
        try:
            wait.until(EC.presence_of_element_located((By.XPATH, "//*[contains(text(), '24/7:')]")))
            time.sleep(5) 
        except:
            logging.critical("[!] Grid failed to load.")
            raise Exception("Grid timeout")

        # --- 3. GET CHANNEL NAMES ---
        # We grab the names first so we can iterate by text
        elements = driver.find_elements(By.XPATH, "//*[contains(text(), '24/7:')]")
        channel_names = [e.text.strip() for e in elements if e.text.strip()]
        logging.info(f"[*] Found {len(channel_names)} channels to process.")

        # --- 4. PROCESS LOOP ---
        for i, raw_name in enumerate(channel_names):
            clean_name = raw_name.replace("24/7:", "").strip()
            logging.info(f"[{i+1}/{len(channel_names)}] Processing: {clean_name}")
            
            try:
                # A. Find the text element
                text_el = driver.find_element(By.XPATH, f"//*[contains(text(), '{raw_name}')]")
                
                # B. Find the PARENT LINK (Crucial Fix)
                # We climb up the HTML tree until we find an <a> tag
                parent_link = text_el.find_element(By.XPATH, "./ancestor::a")
                
                # C. Click and Verify Navigation
                current_url = driver.current_url
                driver.execute_script("arguments[0].click();", parent_link)
                
                # Wait for URL to change (max 5 seconds)
                try:
                    WebDriverWait(driver, 5).until(EC.url_changes(current_url))
                    logging.info("    [+] Navigation confirmed.")
                except:
                    logging.warning("    [!] URL did not change. Click might have failed.")
                    continue # Skip to next channel if we didn't move

                # D. Force Play & Sniff
                time.sleep(2) # Wait for DOM
                
                # Try to press play button if it exists
                try:
                    driver.execute_script("document.getElementsByTagName('video')[0].play()")
                    logging.info("    [+] Sent 'Play' command.")
                except:
                    pass

                time.sleep(6) # Listen for network traffic
                
                found_link = None
                logs = driver.get_log("performance")
                for entry in logs:
                    try:
                        message = json.loads(entry["message"])["message"]
                        if message["method"] == "Network.requestWillBeSent":
                            url = message["params"]["request"]["url"]
                            if ".m3u8" in url and "http" in url:
                                found_link = url
                                if "token" in url: break
                    except:
                        continue

                if found_link:
                    logging.info(f"    [+] Found Stream!")
                    valid_streams.append({'name': clean_name, 'link': found_link})
                else:
                    logging.warning("    [-] No M3U8 found.")

                # E. Go Back safely
                driver.back()
                wait.until(EC.presence_of_element_located((By.XPATH, "//*[contains(text(), '24/7:')]")))
                time.sleep(2)

            except Exception as e:
                logging.error(f"    [!] Failed: {e}")
                # Reset to grid if lost
                driver.get(BASE_URL)
                time.sleep(2)
                try:
                    driver.find_element(By.XPATH, "//*[contains(text(), '24/7 Channels')]").click()
                    time.sleep(3)
                except:
                    pass

    except Exception as e:
        logging.critical(f"Global Crash: {e}")
        traceback.print_exc()

    finally:
        if driver:
            driver.save_screenshot("final_debug.png")
            driver.quit()
        
        if valid_streams:
            with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
                f.write("#EXTM3U\n")
                for stream in valid_streams:
                    f.write(f'#EXTINF:-1 group-title="TimStreams",{stream["name"]}\n')
                    f.write(f'{stream["link"]}\n')
            logging.info(f"[*] Saved {len(valid_streams)} streams.")

if __name__ == "__main__":
    main()
