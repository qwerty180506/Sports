import time
import re
import concurrent.futures
from urllib.parse import unquote
from bs4 import BeautifulSoup

# Selenium Imports
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
OUTPUT_FILE = "timstreams_force.m3u"
MAX_WORKERS = 3
TIMEOUT = 30

def setup_driver():
    """Creates a stealthy Chrome instance."""
    chrome_options = Options()
    chrome_options.add_argument("--headless") 
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    
    # Anti-Detection: Disable 'AutomationControlled' flag
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=chrome_options)

def get_channels():
    print(f"[*] Navigating to {BASE_URL}...")
    driver = setup_driver()
    links_found = []
    
    try:
        driver.get(BASE_URL)
        wait = WebDriverWait(driver, TIMEOUT)
        
        # --- STEP 1: FORCE THE CLICK ---
        print("[*] Looking for '24/7 Channels' button...")
        
        # Take a 'Before' screenshot to verify we are on the homepage
        driver.save_screenshot("debug_01_homepage.png")
        
        try:
            # Try to find the button by text
            btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//*[contains(text(), '24/7 Channels')]")))
            
            # Click strategy: JavaScript click (most reliable for SPAs)
            driver.execute_script("arguments[0].click();", btn)
            print("[*] Click command sent.")
            
        except Exception as e:
            print(f"[!] Could not click button: {e}")
            return []

        # --- STEP 2: VERIFY PAGE LOAD ---
        print("[*] Waiting for 'Refresh Category' or 'Search' to appear...")
        try:
            # We wait for the 'Refresh Category' button shown in your screenshot
            # OR the 'All Genres' dropdown. This confirms we moved pages.
            wait.until(EC.presence_of_element_located((By.XPATH, "//*[contains(text(), 'Refresh Category') or contains(text(), 'All Genres')]")))
            print("[+] Page transition successful!")
        except:
            print("[!] Verification failed. Taking debug screenshot.")
            driver.save_screenshot("debug_02_click_failed.png")
            # We continue anyway, just in case scraping still works
            
        # Small buffer for grid images to render
        time.sleep(5)
        
        # --- STEP 3: DUMP HTML & PARSE WITH SOUP ---
        # Selenium is sometimes bad at finding deep elements. We dump the whole HTML and use BeautifulSoup.
        print("[*] Dumping HTML for parsing...")
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        
        # Strategy A: Find all 'a' tags
        all_links = soup.find_all('a', href=True)
        print(f"[*] Found {len(all_links)} total links in HTML.")
        
        blocklist = ['donate', 'login', 'register', 'discord', 'policy', 'multiview', 'upcoming', 'replay']
        
        for link in all_links:
            href = link['href']
            text = link.get_text(strip=True)
            
            # Filter bad links
            if not href or href == "#" or href == BASE_URL or "javascript" in href:
                continue
            if any(bad in href.lower() for bad in blocklist) or any(bad in text.lower() for bad in blocklist):
                continue
                
            # If no text, try to guess name from URL
            if not text:
                text = href.split('/')[-1].replace('-', ' ').title()
            
            # Save valid channel
            if not any(d['url'] == href for d in links_found):
                links_found.append({'name': text, 'url': href, 'type': 'standard'})

        # Strategy B: Find "Tune In" Buttons (If user is on Live TV page)
        # Look for elements with "Tune In" text
        tune_in_buttons = soup.find_all(string=re.compile("Tune In"))
        for text_node in tune_in_buttons:
            # Walk up to find the parent button or div
            parent = text_node.parent
            # Look for onclick
            onclick = parent.get('onclick')
            if not onclick:
                # Go up one more level
                onclick = parent.parent.get('onclick')
            
            if onclick:
                 match = re.search(r"['\"](https?://.*?)['\"]", onclick)
                 if match:
                     url = match.group(1)
                     name = "Live Channel" # Placeholder
                     if not any(d['url'] == url for d in links_found):
                         links_found.append({'name': name, 'url': url, 'type': 'live'})

    except Exception as e:
        print(f"[!] Critical Error: {e}")
        driver.save_screenshot("debug_crash.png")
    finally:
        driver.quit()
        
    print(f"[*] Total Channels Found: {len(links_found)}")
    return links_found

def process_channel(channel_info):
    driver = setup_driver()
    m3u8_link = None
    
    try:
        driver.get(channel_info['url'])
        time.sleep(3) 
        
        page_source = driver.page_source
        
        # Regex to find .m3u8 links
        regex_list = [
            r'(https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*)',
            r'(https?%3A%2F%2F[^\s"\'<>]+\.m3u8)',
        ]
        
        for regex in regex_list:
            matches = re.findall(regex, page_source)
            if matches:
                link = matches[0].strip('",\'')
                if "%3A" in link:
                    link = unquote(link)
                m3u8_link = link
                break
        
        # Fallback: Check iframes
        if not m3u8_link:
            soup = BeautifulSoup(page_source, 'html.parser')
            iframes = soup.find_all('iframe', src=True)
            for frame in iframes:
                if ".m3u8" in frame['src']:
                    m3u8_link = frame['src']
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
    channels = get_channels()
    
    if not channels:
        print("[!] No channels found. Check 'debug_02_click_failed.png' in Artifacts.")
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
