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
OUTPUT_FILE = "timstreams_v21.m3u"
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
    
    # MOBILE EMULATION (iPhone 14 Pro)
    mobile_emulation = {
        "deviceMetrics": { "width": 393, "height": 852, "pixelRatio": 3.0 },
        "userAgent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1"
    }
    options.add_experimental_option("mobileEmulation", mobile_emulation)
    
    # Enable Network Logging
    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=options)

def mobile_tap_center(driver):
    """
    Simulates a finger tap on the center of the mobile screen.
    """
    try:
        # Tap coordinates (approx center of iPhone screen)
        driver.execute_script("""
            var elem = document.elementFromPoint(196, 426);
            if(elem) {
                var touchStart = new TouchEvent('touchstart', {bubbles: true});
                var touchEnd = new TouchEvent('touchend', {bubbles: true});
                var click = new MouseEvent('click', {bubbles: true});
                elem.dispatchEvent(touchStart);
                elem.dispatchEvent(touchEnd);
                elem.dispatchEvent(click);
                console.log('Mobile Tap dispatched on:', elem);
            }
        """)
        logging.info("    [+] Dispatched Mobile Tap.")
    except Exception as e:
        logging.warning(f"    [!] Tap failed: {e}")

def check_logs(driver):
    logs = driver.get_log("performance")
    for entry in logs:
        try:
            message = json.loads(entry["message"])["message"]
            if message["method"] == "Network.requestWillBeSent":
                url = message["params"]["request"]["url"]
                # Broader filter for mobile streams
                if ".m3u8" in url or ".m3u" in url:
                    if "http" in url: return url
        except:
            continue
    return None

def main():
    driver = None
    valid_streams = []
    
    try:
        logging.info("[*] Starting Scraper v21.0 (Mobile Mode)...")
        driver = setup_driver()
        wait = WebDriverWait(driver, TIMEOUT)
        
        # --- 1. EXTRACT CHANNELS (Desktop view might be different on mobile, so we extract carefully) ---
        driver.get(BASE_URL)
        logging.info("[*] Navigating to Home...")
        
        # On Mobile, the menu might be behind a "Hamburger" icon.
        # But usually, the "24/7 Channels" text is still there or reachable.
        try:
            # Try finding the text link directly
            try:
                btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//*[contains(text(), '24/7 Channels')]")))
                driver.execute_script("arguments[0].click();", btn)
            except:
                # If fail, try clicking hamburger menu first (common class names)
                logging.info("[!] Direct link not found. Looking for mobile menu...")
                menu_btn = driver.find_element(By.CSS_SELECTOR, ".navbar-toggler, .menu-icon, .fa-bars")
                driver.execute_script("arguments[0].click();", menu_btn)
                time.sleep(1)
                btn = driver.find_element(By.XPATH, "//*[contains(text(), '24/7 Channels')]")
                driver.execute_script("arguments[0].click();", btn)

            # Wait for buttons
            wait.until(EC.presence_of_element_located((By.CLASS_NAME, "btn-watch")))
            time.sleep(2)
            
            # Extract
            buttons = driver.find_elements(By.CLASS_NAME, "btn-watch")
            channels = []
            for btn in buttons:
                try:
                    onclick = btn.get_attribute("onclick")
                    # On mobile, structure might be tighter, so we use safe navigation
                    raw_name = "Unknown"
                    try:
                        raw_name = btn.find_element(By.XPATH, "./../h3").text.strip().replace("24/7:", "").strip()
                    except:
                        # Fallback for name
                        raw_name = f"Channel {len(channels)+1}"

                    match = re.search(r"['\"](.*?)['\"]", onclick)
                    if match:
                        full_url = urljoin(BASE_URL, match.group(1))
                        if not any(x['url'] == full_url for x in channels):
                            channels.append({'name': raw_name, 'url': full_url})
                except:
                    continue
            logging.info(f"[*] Found {len(channels)} channels.")

        except Exception as e:
            logging.critical(f"[!] Menu navigation failed: {e}")
            raise e

        # --- 2. VISIT & TAP ---
        for i, ch in enumerate(channels):
            logging.info(f"[{i+1}/{len(channels)}] Visiting: {ch['name']}")
            
            try:
                driver.get(ch['url'])
                time.sleep(3)
                
                found_link = None
                
                # Check for iframes
                iframes = driver.find_elements(By.TAG_NAME, "iframe")
                
                if iframes:
                    # Mobile often puts player in first iframe
                    driver.switch_to.frame(iframes[0])
                    time.sleep(1)
                    mobile_tap_center(driver)
                    time.sleep(8)
                    found_link = check_logs(driver)
                    driver.switch_to.default_content()
                
                if not found_link:
                    # Try Main Page Tap
                    mobile_tap_center(driver)
                    time.sleep(8)
                    found_link = check_logs(driver)

                if found_link:
                    logging.info(f"    [+] SUCCESS: {found_link[:60]}...")
                    valid_streams.append({'name': ch['name'], 'link': found_link})
                else:
                    logging.warning("    [-] Failed.")

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
