import time
import re
import concurrent.futures
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# --- CONFIGURATION ---
BASE_URL = "https://timstreams.site/"
OUTPUT_FILE = "timstreams_247.m3u"
MAX_WORKERS = 2  # Keep low to avoid blocking
TIMEOUT = 20

def setup_driver():
    """Creates a headless Chrome instance with anti-detection."""
    chrome_options = Options()
    chrome_options.add_argument("--headless") 
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080") # Important for some layouts
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36")
    
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=chrome_options)

def get_247_channel_list():
    print(f"[*] Navigating to {BASE_URL}...")
    driver = setup_driver()
    links_found = []
    
    try:
        driver.get(BASE_URL)
        original_window = driver.current_window_handle
        
        # 1. Click '24/7 Channels'
        wait = WebDriverWait(driver, TIMEOUT)
        print("[*] Looking for '24/7 Channels' button...")
        category_btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//*[contains(text(), '24/7 Channels')]")))
        category_btn.click()
        
        time.sleep(5) # Generous wait for animation/load

        # 2. Check for New Tab
        if len(driver.window_handles) > 1:
            print("[!] New tab detected. Switching...")
            driver.switch_to.window(driver.window_handles[-1])

        # 3. Scrape ALL links (Removed domain filter)
        print(f"[*] Scanning for channels on: {driver.current_url}")
        elements = driver.find_elements(By.TAG_NAME, "a")
        
        # Keywords to skip
        ignore_list = ['donate', 'login', 'register', 'discord', 'contact', 'policy', 'multiview', 'upcoming', 'replay']

        for elem in elements:
            try:
                href = elem.get_attribute("href")
                text = elem.text.strip()
                
                if href and text:
                    # Filter out obvious non-channel links
                    if any(bad in text.lower() for bad in ignore_list):
                        continue
                    
                    # Filter out empty or javascript links
                    if "javascript" in href or href == BASE_URL:
                        continue

                    # Avoid duplicates
                    if not any(d['url'] == href for d in links_found):
                        links_found.append({'name': text, 'url': href})
            except:
                continue
        
        # DEBUG: Take a screenshot if no links found
        if len(links_found) < 3:
            print("[!] Warning: Very few links found. Saving debug screenshot...")
            driver.save_screenshot("debug_page.png")

    except Exception as e:
        print(f"[!] Error finding channel list: {e}")
        driver.save_screenshot("debug_error.png")
    finally:
        driver.quit()
        
    print(f"[*] Found {len(links_found)} potential channels.")
    return links_found

def process_channel(channel_info):
    driver = setup_driver()
    m3u8_link = None
    
    try:
        driver.get(channel_info['url'])
        time.sleep(4) # Wait for player
        
        # Scan full page source (HTML + JS)
        page_source = driver.page_source
        
        # Regex for m3u8
        regex = r'(https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*)'
        matches = re.findall(regex, page_source)
        
        if matches:
            m3u8_link = matches[0].strip('",\'')
        else:
            # Fallback: Check iframes specifically
            iframes = driver.find_elements(By.TAG_NAME, "iframe")
            for iframe in iframes:
                src = iframe.get_attribute("src")
                if src and ".m3u8" in src:
                    m3u8_link = src
                    break

    except Exception:
        pass
    finally:
        driver.quit()
        
    if m3u8_link:
        print(f"   [+] {channel_info['name']}")
        return {'name': channel_info['name'], 'link': m3u8_link}
    else:
        print(f"   [-] {channel_info['name']}: Not found")
        return None

def main():
    channels = get_247_channel_list()
    
    if not channels:
        print("[!] No channels found. Check 'debug_page.png' in the repo.")
        return

    valid_streams = []
    print(f"[*] Extracting streams from {len(channels)} channels...")
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_channel = {executor.submit(process_channel, ch): ch for ch in channels}
        for future in concurrent.futures.as_completed(future_to_channel):
            result = future.result()
            if result:
                valid_streams.append(result)

    if valid_streams:
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n")
            for stream in valid_streams:
                f.write(f'#EXTINF:-1 group-title="TimStreams",{stream["name"]}\n')
                f.write(f'{stream["link"]}\n')
        print(f"[*] Saved {len(valid_streams)} streams to {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
