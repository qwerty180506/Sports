import time
import json
import re
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# --- CONFIGURATION ---
BASE_URL = "https://timstreams.site/"
OUTPUT_FILE = "timstreams_ultimate.m3u"
TIMEOUT = 30

def setup_driver():
    options = Options()
    options.add_argument("--headless") 
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    # Enable Network Logging (The "Sniffer")
    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=options)

def main():
    driver = setup_driver()
    valid_streams = []
    
    try:
        print(f"[*] Navigating to {BASE_URL}...")
        driver.get(BASE_URL)
        wait = WebDriverWait(driver, TIMEOUT)
        
        # --- 1. NAVIGATE TO 24/7 PAGE ---
        print("[*] Finding '24/7 Channels' button...")
        try:
            # Find button by text (robust match)
            btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//*[contains(text(), '24/7 Channels')]")))
            driver.execute_script("arguments[0].click();", btn)
        except Exception as e:
            print("[!] Navigation failed. Saving screenshot.")
            driver.save_screenshot("debug_nav_fail.png")
            raise e

        # --- 2. WAIT FOR GRID TO LOAD ---
        print("[*] Waiting for channels...")
        try:
            # We explicitly wait for the text "24/7:" which appears on every card in your screenshot
            wait.until(EC.presence_of_element_located((By.XPATH, "//*[contains(text(), '24/7:')]")))
            time.sleep(5) # Let all images load
        except:
            print("[!] Grid load timed out. dumping HTML...")
            with open("debug_source.html", "w", encoding="utf-8") as f:
                f.write(driver.page_source)
            raise Exception("Channels did not load.")

        # --- 3. IDENTIFY CHANNELS ---
        # Instead of links, we find the text elements containing "24/7:"
        # Then we find their clickable parents.
        channel_elements = driver.find_elements(By.XPATH, "//*[contains(text(), '24/7:')]")
        print(f"[*] Found {len(channel_elements)} visual channel cards.")
        
        # We store the NAMES now, because the elements will become "stale" once we click one.
        channel_names = [elem.text.strip() for elem in channel_elements if elem.text.strip()]
        
        # --- 4. THE LOOP: CLICK -> SNIFF -> BACK ---
        for i, raw_name in enumerate(channel_names):
            clean_name = raw_name.replace("24/7:", "").strip()
            print(f"[{i+1}/{len(channel_names)}] Processing: {clean_name}")
            
            try:
                # A. Re-Find the element (because page refreshed/changed)
                # We find the specific text element again
                target_el = driver.find_element(By.XPATH, f"//*[contains(text(), '{raw_name}')]")
                
                # B. Click it (Force click parent if needed)
                # We assume the text is inside the clickable card
                driver.execute_script("arguments[0].click();", target_el)
                
                # C. Wait & Sniff
                time.sleep(6) # Wait for player to start request
                
                found_link = None
                logs = driver.get_log("performance")
                
                for entry in logs:
                    message = json.loads(entry["message"])["message"]
                    if message["method"] == "Network.requestWillBeSent":
                        url = message["params"]["request"]["url"]
                        if ".m3u8" in url and "http" in url:
                            found_link = url
                            if "token" in url: break # Prefer token links
                
                if found_link:
                    print(f"    [+] Success! Found stream.")
                    valid_streams.append({'name': clean_name, 'link': found_link})
                else:
                    print(f"    [-] No .m3u8 traffic captured.")
                    
                # D. Go Back to list
                driver.back()
                # Wait for grid to reappear
                wait.until(EC.presence_of_element_located((By.XPATH, "//*[contains(text(), '24/7:')]")))
                time.sleep(2)

            except Exception as e:
                print(f"    [!] Error on channel: {e}")
                # Try to recover navigation
                driver.get(BASE_URL)
                time.sleep(3)
                driver.find_element(By.XPATH, "//*[contains(text(), '24/7 Channels')]").click()
                time.sleep(3)

    except Exception as e:
        print(f"[!] Critical Error: {e}")
    finally:
        driver.quit()

    # --- 5. SAVE FILE ---
    if valid_streams:
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n")
            for stream in valid_streams:
                f.write(f'#EXTINF:-1 group-title="TimStreams",{stream["name"]}\n')
                f.write(f'{stream["link"]}\n')
        print(f"[*] DONE. Saved {len(valid_streams)} streams to {OUTPUT_FILE}")
    else:
        print("[!] No streams found.")

if __name__ == "__main__":
    main()
