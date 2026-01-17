import time
import re
import concurrent.futures
from urllib.parse import unquote
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
OUTPUT_FILE = "timstreams_universal.m3u"
MAX_WORKERS = 3
TIMEOUT = 30

def setup_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless") 
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36")
    
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=chrome_options)

def get_channels():
    print(f"[*] Navigating to {BASE_URL}...")
    driver = setup_driver()
    links_found = []
    
    try:
        driver.get(BASE_URL)
        wait = WebDriverWait(driver, TIMEOUT)
        
        # --- ATTEMPT 1: CLICK 24/7 CHANNELS ---
        print("[*] Attempting to enter '24/7 Channels'...")
        try:
            # Try finding the button by text
            btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//*[contains(text(), '24/7 Channels')]")))
            driver.execute_script("arguments[0].click();", btn)
            time.sleep(5)
        except Exception as e:
            print(f"[!] Click warning: {e}")

        # --- SCROLLING ---
        print("[*] Scrolling to load content...")
        for _ in range(3):
            driver.find_element(By.TAG_NAME, "body").send_keys(Keys.END)
            time.sleep(2)

        # --- STRATEGY A: Standard Links (Cartoons/Movies) ---
        print("[*] Scanning for Standard Links (<a> tags)...")
        elements = driver.find_elements(By.TAG_NAME, "a")
        for elem in elements:
            try:
                href = elem.get_attribute("href")
                text = elem.text.strip() or elem.get_attribute("innerText").strip()
                
                if href and BASE_URL in href and "javascript" not in href:
                    # Filter out system links
                    if any(x in href.lower() for x in ['donate', 'login', 'register', 'discord', 'policy']):
                        continue
                    
                    # If it looks like a channel
                    if not any(d['url'] == href for d in links_found):
                        name = text if text else href.split("/")[-1].replace("-", " ").title()
                        links_found.append({'name': name, 'url': href, 'type': 'standard'})
            except:
                continue

        # --- STRATEGY B: "Tune In" Buttons (Live TV/Sports) ---
        # This fixes the issue seen in your screenshot where only "Tune In" buttons exist
        print("[*] Scanning for 'Tune In' Buttons (Javascript Links)...")
        buttons = driver.find_elements(By.XPATH, "//*[contains(text(), 'Tune In')]")
        
        for btn in buttons:
            try:
                # 1. Check if the button itself has an onclick
                raw_onclick = btn.get_attribute("onclick")
                
                # 2. If not, check the parent container
                if not raw_onclick:
                    parent = btn.find_element(By.XPATH, "./..")
                    raw_onclick = parent.get_attribute("onclick")
                
                # 3. If not, check if it's wrapped in an <a> tag without a visible href
                parent_a = btn.find_element(By.XPATH, "./..") if btn.tag_name != "a" else btn
                href = parent_a.get_attribute("href")

                target_url = None
                
                if href:
                    target_url = href
                elif raw_onclick:
                    # Extract URL from: window.location.href='https://...' or open('https://...')
                    match = re.search(r"['\"](https?://.*?)['\"]", raw_onclick)
                    if match:
                        target_url = match.group(1)

                if target_url:
                    # Try to find the Name (usually in a sibling div or h3)
                    # We go up to the card container and find the title
                    try:
                        card = btn.find_element(By.XPATH, "./ancestor::div[contains(@class, 'card') or contains(@class, 'box')]")
                        name_el = card.find_element(By.TAG_NAME, "h3") or card.find_element(By.TAG_NAME, "h4")
                        name = name_el.text.strip()
                    except:
                        name = "Live Channel"

                    if not any(d['url'] == target_url for d in links_found):
                         links_found.append({'name': name, 'url': target_url, 'type': 'live'})
            except Exception as e:
                continue

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
        time.sleep(4) 
        
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
        
        # Fallback for iframes
        if not m3u8_link:
            iframes = driver.find_elements(By.TAG_NAME, "iframe")
            for frame in iframes:
                src = frame.get_attribute("src")
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
        print(f"   [-] {channel_info['name']}: No stream found")
        return None

def main():
    channels = get_channels()
    
    if not channels:
        print("[!] No channels found. Use the debug screenshot to investigate.")
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
