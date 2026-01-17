import time
import re
import concurrent.futures
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# --- CONFIGURATION ---
BASE_URL = "https://timstreams.site/"
OUTPUT_FILE = "timstreams_all.m3u"
MAX_WORKERS = 3  # Increased slightly for speed
TIMEOUT = 25 

def setup_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless") 
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    # Mask as a real user to avoid blocks
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36")
    
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=chrome_options)

def get_all_channels():
    print(f"[*] Navigating to {BASE_URL}...")
    driver = setup_driver()
    links_found = []
    
    try:
        driver.get(BASE_URL)
        wait = WebDriverWait(driver, TIMEOUT)
        
        # 1. Click '24/7 Channels' Button
        print("[*] Entering '24/7 Channels' section...")
        category_btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//*[contains(text(), '24/7 Channels')]")))
        driver.execute_script("arguments[0].click();", category_btn)
        
        # 2. Wait for Content to Load (Search Bar)
        print("[*] Waiting for content...")
        try:
            wait.until(EC.presence_of_element_located((By.XPATH, "//input[@placeholder='Search 24/7 channels...']")))
        except:
            time.sleep(5) # Fallback wait

        # 3. AUTO-SCROLL (Crucial for lazy-loaded channels)
        print("[*] Scrolling to load all channels...")
        last_height = driver.execute_script("return document.body.scrollHeight")
        for i in range(3): # Scroll down 3 times
            driver.find_element(By.TAG_NAME, "body").send_keys(Keys.END)
            time.sleep(2)
            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height
            
        # 4. Scrape ALL Links (Blocklist Strategy)
        print(f"[*] Scanning all links on page...")
        elements = driver.find_elements(By.TAG_NAME, "a")
        
        # Keywords to IGNORE (System links)
        blocklist = [
            'donate', 'login', 'register', 'discord', 'contact', 'policy', 
            'multiview', 'upcoming', 'replay', 'dmca', 'home', 'back', 'search'
        ]

        for elem in elements:
            try:
                href = elem.get_attribute("href")
                text = elem.text.strip()
                
                # Basic cleanup
                if not href or "javascript" in href or href == BASE_URL:
                    continue

                # Filter: If the text or URL contains blocked words, skip it
                if any(bad_word in text.lower() for bad_word in blocklist):
                    continue
                if any(bad_word in href.lower() for bad_word in blocklist):
                    continue
                
                # If it passed the blocklist, it's likely a channel
                # We use the text as the name, or fallback to the URL slug
                name = text if text else href.split('/')[-1].replace('-', ' ').title()
                
                if not any(d['url'] == href for d in links_found):
                    links_found.append({'name': name, 'url': href})
            except:
                continue

    except Exception as e:
        print(f"[!] Error finding channels: {e}")
        driver.save_screenshot("debug_failed_list.png")
    finally:
        driver.quit()
        
    print(f"[*] Found {len(links_found)} potential channels.")
    return links_found

def process_channel(channel_info):
    driver = setup_driver()
    m3u8_link = None
    
    try:
        driver.get(channel_info['url'])
        time.sleep(4) # Wait for player to init
        
        page_source = driver.page_source
        
        # Regex to find .m3u8 links (Standard, Encoded, or Hidden in JSON)
        regex_list = [
            r'(https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*)',  # Standard
            r'(https?%3A%2F%2F[^\s"\'<>]+\.m3u8)',      # Encoded
        ]
        
        for regex in regex_list:
            matches = re.findall(regex, page_source)
            if matches:
                link = matches[0].strip('",\'')
                # Fix encoded URLs
                if "%3A" in link:
                    from urllib.parse import unquote
                    link = unquote(link)
                
                # Filter out "token" noise if it looks like a false positive (optional)
                if "http" in link:
                    m3u8_link = link
                    break
        
    except Exception:
        pass
    finally:
        driver.quit()
        
    if m3u8_link:
        print(f"   [+] {channel_info['name']}")
        return {'name': channel_info['name'], 'link': m3u8_link}
    else:
        print(f"   [-] {channel_info['name']}: No stream found")
        return None

def main():
    channels = get_all_channels()
    
    if not channels:
        print("[!] No channels found. Check 'debug_failed_list.png' in artifacts.")
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
                # Clean up the name for the playlist
                clean_name = stream["name"].replace("24/7:", "").strip()
                f.write(f'#EXTINF:-1 group-title="TimStreams",{clean_name}\n')
                f.write(f'{stream["link"]}\n')
        print(f"[*] Success! Saved {len(valid_streams)} streams to {OUTPUT_FILE}")
    else:
        print("[!] No valid streams extracted.")

if __name__ == "__main__":
    main()
