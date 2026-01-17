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
OUTPUT_FILE = "timstreams_v16.m3u"
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

def try_force_play(driver):
    """
    Attempts to start the video by clicking common overlay buttons or using JS.
    """
    # 1. Try finding generic "Big Play Buttons" (Clappr, VideoJS, JWPlayer)
    play_selectors = [
        ".vjs-big-play-button",
        ".jw-display-icon-container",
        ".clappr-big-play-button",
        ".plyr__control--overlaid",
        "button[class*='play']",
        "div[class*='play']"
    ]
    
    for selector in play_selectors:
        try:
            btn = driver.find_element(By.CSS_SELECTOR, selector)
            if btn.is_displayed():
                driver.execute_script("arguments[0].click();", btn)
                logging.info(f"    [+] Clicked play button: {selector}")
                time.sleep(1)
                return
        except:
            continue

    # 2. Fallback: JavaScript Force Play
    try:
        driver.execute_script("""
            var v = document.querySelector('video');
            if(v) { v.muted = true; v.play(); }
        """)
        logging.info("    [+] Sent JS Play command.")
    except:
        pass

def main():
    driver = None
    valid_streams = []
    
    try:
        logging.info("[*] Starting Scraper v16.0 (Player Breaker)...")
        driver = setup_driver()
        wait = WebDriverWait(driver, TIMEOUT)
        
        # --- 1. NAVIGATE & EXTRACT (Proven to work) ---
        logging.info("[*] Extracting channel list...")
        driver.get(BASE_URL)
        
        try:
            btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//*[contains(text(), '24/7 Channels')]")))
            driver.execute_script("arguments[0].click();", btn)
            
            # Wait for buttons
            wait.until(EC.presence_of_element_located((By.CLASS_NAME, "btn-watch")))
            time.sleep(3)
            
            buttons = driver.find_elements(By.CLASS_NAME, "btn-watch")
            channels_to_visit = []
            
            for btn in buttons:
                try:
                    onclick_text = btn.get_attribute("onclick")
                    parent_card = btn.find_element(By.XPATH, "./..")
                    raw_name = parent_card.find_element(By.TAG_NAME, "h3").text.strip()
                    clean_name = raw_name.replace("24/7:", "").strip()
                    
                    match = re.search(r"['\"](.*?)['\"]", onclick_text)
                    if match:
                        full_url = urljoin(BASE_URL, match.group(1))
                        if not any(x['url'] == full_url for x in channels_to_visit):
                             channels_to_visit.append({'name': clean_name, 'url': full_url})
                except:
                    continue
            
            logging.info(f"[*] Found {len(channels_to_visit)} channels.")

        except Exception as e:
            logging.critical("[!] Menu navigation failed.")
            raise e

        # --- 2. VISIT & SNIFF (Updated for Iframes) ---
        for i, channel in enumerate(channels_to_visit):
            logging.info(f"[{i+1}/{len(channels_to_visit)}] Visiting: {channel['name']}")
            
            try:
                driver.get(channel['url'])
                time.sleep(2)
                
                # --- IFRAME HANDLING ---
                # Many streams are inside an iframe. We must switch to it.
                iframes = driver.find_elements(By.TAG_NAME, "iframe")
                if iframes:
                    logging.info("    [i] Iframe detected. Switching context...")
                    driver.switch_to.frame(iframes[0])
                    time.sleep(1)

                # Try to press play (inside iframe or main page)
                try_force_play(driver)
                
                # Wait for network traffic
                time.sleep(6)
                
                # --- SNIFFING ---
                # Note: Network logs capture ALL traffic, even from iframes, 
                # so we don't strictly need to be inside the iframe to *see* the log,
                # but we needed to switch to *click* the play button.
                
                found_link = None
                logs = driver.get_log("performance")
                
                for entry in logs:
                    try:
                        message = json.loads(entry["message"])["
