import time
import random
import os
from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.edge.options import Options
from selenium.webdriver.edge.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# --- Configuration ---
NUMBER_OF_SEARCHES = 50
MIN_WAIT = 3
MAX_WAIT = 6

def create_edge_driver(edge_options):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    bundled_driver = os.path.join(script_dir, "msedgedriver.exe")
    attempts = []

    try:
        # Selenium Manager usually downloads/selects the correct driver for the
        # installed Edge version, which makes the script more shareable.
        print("Starting Edge with Selenium Manager...")
        return webdriver.Edge(options=edge_options)
    except WebDriverException as exc:
        attempts.append(f"Selenium Manager failed: {exc}")

    if os.path.exists(bundled_driver):
        try:
            print(f"Falling back to bundled driver: {bundled_driver}")
            service = Service(executable_path=bundled_driver)
            return webdriver.Edge(service=service, options=edge_options)
        except WebDriverException as exc:
            attempts.append(f"Bundled driver failed: {exc}")

    error_lines = [
        "Unable to start Microsoft Edge.",
        "Make sure Microsoft Edge is installed and up to date.",
        "If you are sharing this script, ask the other person to install Selenium with:",
        "pip install selenium",
    ]
    if os.path.exists(bundled_driver):
        error_lines.append(
            "The bundled msedgedriver.exe may also need to match their Edge version."
        )
    error_lines.extend(attempts)
    raise RuntimeError("\n".join(error_lines))

def get_random_search_query():
    search_intents = [
        "how to", "best", "top 10", "latest news about", "history of", 
        "why is", "reviews for", "cheap", "guide to", "alternatives to"
    ]
    
    topics = [
        "python programming", "artificial intelligence", "stock market", "cryptocurrency",
        "gaming laptops", "wireless headphones", "electric cars", "sustainable living",
        "remote work tips", "digital marketing", "healthy recipes", "yoga for beginners",
        "marvel movies", "space exploration", "new iphone", "android features",
        "travel destinations 2025", "home workout"
    ]
    
    intent = random.choice(search_intents)
    topic = random.choice(topics)
    
    return f"{intent} {topic}"

def perform_typing_searches():
    edge_options = Options()
    edge_options.add_argument("--start-maximized")
    # edge_options.add_argument("--inprivate") # Optional: Use Incognito mode
    
    driver = create_edge_driver(edge_options)
    
    try:
        print("Browser started...")
        
        # Open Bing initially to have a starting point
        driver.get("https://www.bing.com")
        time.sleep(2)

        for i in range(NUMBER_OF_SEARCHES):
            # 1. Identify the current tab (which will become the 'old' tab)
            old_tab = driver.current_window_handle
            
            # 2. Open a NEW tab and switch to it
            driver.switch_to.new_window('tab')
            
            # 3. Go to Bing homepage in the new tab
            driver.get("https://www.bing.com")
            
            # 4. Generate the query
            query = get_random_search_query()
            print(f"[{i+1}/{NUMBER_OF_SEARCHES}] Typing: '{query}'")
            
            # 5. Find the search box and Type the query
            # We use WebDriverWait to ensure the box is ready before typing
            try:
                # Bing's search box usually has the name attribute "q"
                search_box = WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located((By.NAME, "q"))
                )
                
                search_box.clear() # Clear any pre-filled text
                search_box.send_keys(query) # Type the plain text
                time.sleep(0.5) # Tiny pause like a human thinking
                search_box.send_keys(Keys.RETURN) # Press Enter
                
            except Exception as e:
                print(f"Could not find search box: {e}")
                continue

            # 6. Wait for results to load
            time.sleep(random.uniform(MIN_WAIT, MAX_WAIT))
            
            # 7. Close the OLD tab
            driver.switch_to.window(old_tab)
            driver.close()
            
            # 8. Switch back to the NEW tab (the only one left)
            # After closing a tab, Selenium needs to be told explicitly where to look next
            driver.switch_to.window(driver.window_handles[0])

        print("All searches completed successfully.")

    except Exception as e:
        print(f"Critical Error: {e}")

    finally:
        driver.quit()
        print("Browser closed.")

if __name__ == "__main__":
    perform_typing_searches()
