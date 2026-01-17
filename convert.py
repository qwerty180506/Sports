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
MAX_WORKERS = 3  # Simultaneous tabs
TIMEOUT = 15     # Seconds to wait for elements

def setup_driver():
    """Creates a headless Chrome instance."""
    chrome_options = Options()
    chrome_options.add_argument("--headless") 
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--log-level=3")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36")
    
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=chrome_options)

def get_247_channel_list():
    """
    Navigates to Home -> Clicks '24/7 Channels' -> Scrapes Links.
    """
    print(f"[*] Navigating to {BASE_URL}...")
    driver = setup_driver()
    links_found = []
    
    try:
        driver.get(BASE_URL)
        
        # 1. FIND THE '24/7 Channels' BUTTON SEEN IN THE IMAGE
        # We use XPath to find the element containing that exact text.
        print("[*] Looking for '24/7 Channels' section...")
        wait = WebDriverWait(driver, TIMEOUT)
        
        # This XPath finds any element (a, div, button) containing the text "24/7 Channels"
        category_btn = wait.until(
            EC.element_to_be_clickable((By.XPATH, "//*[contains(text(), '24/7 Channels')]"))
        )
        
        # Click to enter the category
        category_btn.click()
        
        # 2. WAIT FOR THE CHANNELS TO LOAD
        # We wait for the URL to change OR for new 'a' tags to appear
        time.sleep(3) # Short sleep to allow page transition/animation
        
        print(f"[*] Scanning channel list on: {driver.current_url}")
        
        # 3. SCRAPE CHANNEL LINKS
        elements = driver.find_elements(By.TAG_NAME, "a")
        
        for elem in elements:
            try:
                href = elem.get_attribute("href")
                text = elem.text.strip()
                
                # Filter: Ensure link is valid and not a navigation link (like 'Home' or 'Donate')
                if href and BASE_URL in href and text:
                    # Exclude the category buttons themselves if they are still visible
                    if "24/7 Channels" in text or "Upcoming" in text:
                        continue
                        
                    # Avoid duplicates
                    if not any(d['url'] == href for d in links_found):
                        links_found.append({'name': text, 'url': href})
            except:
                continue

    except Exception as e:
        print(f"[!] Error finding channel list: {e}")
    finally:
        driver.quit()
        
    print(f"[*] Found {len(links_found)} channels in '24/7' section.")
    return links_found

def process_channel(channel_info):
    """
    Worker: Visits a specific channel URL and extracts the m3u8.
    """
    driver = setup_driver()
    m3u8_link = None
    
    try:
        driver.get(channel_info['url'])
        time.sleep(2) # Allow JS player to load
        
        # Grab source code
        page_source = driver.page_source
        
        # Regex to find .m3u8 links (even if hidden in JS)
        # Matches: http...m3u8 or https...m3u8
        regex = r'(https?://[^\s"\']+\.m3u8[^\s"\']*)'
        
        matches = re.findall(regex, page_source)
        if matches:
            # Clean up the link (remove potential trailing characters from regex capture)
            clean_link = matches[0].strip('",\'')
            if "token" in clean_link or "m3u8" in clean_link:
                m3u8_link = clean_link
        
    except Exception:
        pass
    finally:
        driver.quit()
        
    if m3u8_link:
        print(f"   [+] {channel_info['name']}: Found Stream")
        return {'name': channel_info['name'], 'link': m3u8_link}
    else:
        print(f"   [-] {channel_info['name']}: No stream found")
        return None

def main():
    # Step 1: Get the list of channels from the 24/7 section
    channels = get_247_channel_list()
    
    if not channels:
        print("[!] No channels found. The button text might differ or site is protected.")
        return

    valid_streams = []

    # Step 2: Scrape streams in parallel
    print(f"[*] Extracting streams with {MAX_WORKERS} workers...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_channel = {executor.submit(process_channel, ch): ch for ch in channels}
        
        for future in concurrent.futures.as_completed(future_to_channel):
            result = future.result()
            if result:
                valid_streams.append(result)

    # Step 3: Save to M3U
    if valid_streams:
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n")
            for stream in valid_streams:
                f.write(f'#EXTINF:-1 group-title="24/7 Channels",{stream["name"]}\n')
                f.write(f'{stream["link"]}\n')
        print(f"[*] Success! Saved {len(valid_streams)} channels to {OUTPUT_FILE}")
    else:
        print("[!] No valid streams extracted.")

if __name__ == "__main__":
    main()
