import time
import json
import concurrent.futures
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.desired_capabilities import DesiredCapabilities
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# --- CONFIGURATION ---
BASE_URL = "https://timstreams.site/"
OUTPUT_FILE = "timstreams_ultimate.m3u"
MAX_WORKERS = 1  # Must be 1 for Network Sniffing reliability
TIMEOUT = 30

def setup_driver():
    """Creates a Chrome instance with Network Logging enabled."""
    chrome_options = Options()
    chrome_options.add_argument("--headless") 
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    # Enable Performance Logging (captures network traffic)
    chrome_options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=chrome_options)

def get_channels():
    print(f"[*] Navigating to {BASE_URL}...")
    driver = setup_driver()
    links_found = []
    
    try:
        driver.get(BASE_URL)
        wait = WebDriverWait(driver, TIMEOUT)
        
        # --- STEP 1: FORCE NAVIGATION ---
        print("[*] Finding '24/7 Channels' button...")
        
        # Find ALL buttons with that text
        buttons = driver.find_elements(By.XPATH, "//*[contains(text(), '24/7 Channels')]")
        clicked = False
        
        for btn in buttons:
            if btn.is_displayed():
                print("    - Found visible button. Clicking...")
                driver.execute_script("arguments[0].scrollIntoView(true);", btn)
                time.sleep(1)
                driver.execute_script("arguments[0].click();", btn)
                clicked = True
                break
        
        if not clicked and buttons:
            print("    - No visible button found. Force-clicking the first one...")
            driver.execute_script("arguments[0].click();", buttons[0])

        # --- STEP 2: VERIFY WE LEFT THE HOMEPAGE ---
        print("[*] Waiting for grid to load...")
        try:
            # Wait for the "Search" bar seen in your screenshot
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input[placeholder*='Search']")))
            print("[+] Navigation Successful! We are on the channels page.")
        except:
            print("[!] Navigation Timeout. Taking debug screenshot.")
            driver.save_screenshot("debug_nav_failed.png")
            # If navigation failed, we might still be on homepage. 
            # We return empty to stop wasting time.
            return []

        # --- STEP 3: SCRAPE CHANNELS ---
        print("[*] Scraping channel links...")
        time.sleep(3) # Let images load
        
        elements = driver.find_elements(By.TAG_NAME, "a")
        for elem in elements:
            try:
                href = elem.get_attribute("href")
                text = elem.text.strip()
                
                # Filter for valid channel links
                if href and "timstreams.site" in href and "24/7" in text:
                     # Clean name: "24/7: Bluey" -> "Bluey"
                    name = text.replace("24/7:", "").strip()
                    if not any(d['url'] == href for d in links_found):
                        links_found.append({'name': name, 'url': href})
            except:
                continue
                
    except Exception as e:
        print(f"[!] Error: {e}")
    finally:
        driver.quit()
        
    print(f"[*] Found {len(links_found)} channels.")
    return links_found

def sniff_stream(channel_info):
    """
    Visits the page and listens to the network traffic for .m3u8 files.
    """
    driver = setup_driver()
    stream_url = None
    
    try:
        print(f"    Scanning: {channel_info['name']}...")
        driver.get(channel_info['url'])
        
        # Wait for player to load (iframe or video tag)
        time.sleep(8) 
        
        # 1. Process Network Logs
        logs = driver.get_log("performance")
        
        for entry in logs:
            message = json.loads(entry["message"])["message"]
            
            # We look for 'Network.requestWillBeSent' events
            if message["method"] == "Network.requestWillBeSent":
                url = message["params"]["request"]["url"]
                
                # Check if it is a master playlist
                if ".m3u8" in url:
                    # Filter out sub-playlists (chunks) if possible, usually we want master.m3u8
                    # or index.m3u8.
                    stream_url = url
                    # If we find a tokenized link, it's usually the right one. Break early.
                    if "token" in url:
                        break
        
        # 2. Fallback: Check standard iframe src if sniffing failed
        if not stream_url:
            iframes = driver.find_elements(By.TAG_NAME, "iframe")
            for frame in iframes:
                src = frame.get_attribute("src")
                if src and ".m3u8" in src:
                    stream_url = src
                    break

    except Exception as e:
        print(f"    [!] Error sniffing: {e}")
    finally:
        driver.quit()
        
    if stream_url:
        print(f"    [+] FOUND STREAM: {channel_info['name']}")
        return {'name': channel_info['name'], 'link': stream_url}
    else:
        print(f"    [-] No traffic found: {channel_info['name']}")
        return None

def main():
    channels = get_channels()
    
    if not channels:
        print("[!] No channels found. Check 'debug_nav_failed.png'.")
        return

    valid_streams = []
    print(f"[*] Sniffing streams from {len(channels)} channels (One by one)...")
    
    # We run sequentially (1 worker) because network logging is heavy and mixing logs is bad.
    for channel in channels:
        result = sniff_stream(channel)
        if result:
            valid_streams.append(result)

    if valid_streams:
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n")
            for stream in valid_streams:
                f.write(f'#EXTINF:-1 group-title="TimStreams 24/7",{stream["name"]}\n')
                f.write(f'{stream["link"]}\n')
        print(f"[*] Success! Saved {len(valid_streams)} streams.")
    else:
        print("[!] No streams found.")

if __name__ == "__main__":
    main()
