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
MAX_WORKERS = 3
TIMEOUT = 30

def setup_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless") 
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    # Stealth User Agent
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
        
        # 1. Click '24/7 Channels'
        print("[*] Clicking '24/7 Channels'...")
        try:
            category_btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//*[contains(text(), '24/7 Channels')]")))
            driver.execute_script("arguments[0].click();", category_btn)
        except Exception as e:
            print(f"[!] Click failed: {e}")
            driver.save_screenshot("debug_click_fail.png")
            return []

        # 2. SMART WAIT: Wait until link count increases
        print("[*] Waiting for channels to populate (Target: > 10 links)...")
        max_retries = 10
        for i in range(max_retries):
            # Count visible links
            current_links = driver.find_elements(By.TAG_NAME, "a")
            count = len(current_links)
            print(f"    - Attempt {i+1}: Found {count} links...")
            
            if count > 10:  # If we see more than just header links
                print("    [+] Grid loaded!")
                break
            
            time.sleep(2)
        
        # 3. Auto-Scroll to bottom to trigger any lazy loading
        driver.find_element(By.TAG_NAME, "body").send_keys(Keys.END)
        time.sleep(2)
        
        # 4. Scrape Links
        print(f"[*] Scanning DOM...")
        elements = driver.find_elements(By.TAG_NAME, "a")
        
        # Blocklist for system links
        blocklist = [
            'donate', 'login', 'register', 'discord', 'contact', 'policy', 
            'multiview', 'upcoming', 'replay', 'dmca', 'home', 'mirror'
        ]

        for elem in elements:
            try:
                href = elem.get_attribute("href")
                text = elem.text.strip()
                
                if not href or href == BASE_URL or "javascript" in href:
                    continue
                    
                # Skip blocked words
                if any(bad in text.lower() for bad in blocklist) or any(bad in href.lower() for bad in blocklist):
                    continue

                # Fallback Name Generation
                if not text:
                    # Create name from URL (e.g. /watch/channel-name -> Channel Name)
                    text = href.strip("/").split("/")[-1].replace("-", " ").title()
                
                if not any(d['url'] == href for d in links_found):
                    links_found.append({'name': text, 'url': href})
            except:
                continue
                
        # DEBUG: Take a picture of what we found
        if len(links_found) == 0:
            print("[!] Still 0 channels. Taking screenshot.")
            driver.save_screenshot("debug_empty_grid.png")

    except Exception as e:
        print(f"[!] Error: {e}")
        driver.save_screenshot("debug_crash.png")
    finally:
        driver.quit()
        
    print(f"[*] Final Count: {len(links_found)} channels.")
    return links_found

def process_channel(channel_info):
    driver = setup_driver()
    m3u8_link = None
    
    try:
        driver.get(channel_info['url'])
        time.sleep(4) 
        
        page_source = driver.page_source
        
        # Standard + Encoded + JSON regex
        regex_list = [
            r'(https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*)',
            r'(https?%3A%2F%2F[^\s"\'<>]+\.m3u8)',
        ]
        
        for regex in regex_list:
            matches = re.findall(regex, page_source)
            if matches:
                link = matches[0].strip('",\'')
                if "%3A" in link:
                    from urllib.parse import unquote
                    link = unquote(link)
                
                # Basic validation
                if "http" in link and len(link) > 10:
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
        print(f"   [-] {channel_info['name']}: Not found")
        return None

def main():
    channels = get_all_channels()
    
    if not channels:
        print("[!] No channels. Check 'debug_empty_grid.png'.")
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
                clean_name = stream["name"].replace("24/7:", "").strip()
                f.write(f'#EXTINF:-1 group-title="TimStreams",{clean_name}\n')
                f.write(f'{stream["link"]}\n')
        print(f"[*] Success! Saved {len(valid_streams)} streams.")
    else:
        print("[!] No streams found.")

if __name__ == "__main__":
    main()
