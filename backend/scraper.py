# backend/scraper.py
import time
import re
import logging
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException, WebDriverException, NoSuchElementException,
    ElementClickInterceptedException, StaleElementReferenceException
)
from bs4 import BeautifulSoup
from urllib.parse import urljoin

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Constants ---
FIXTURES_URL = "https://www.iplt20.com/matches/fixtures"
RESULTS_URL = "https://www.iplt20.com/matches/results"
BASE_URL = "https://www.iplt20.com" # Base URL for resolving relative links if needed
SCROLL_PAUSE_TIME = 2
MAX_SCROLL_ATTEMPTS_WITHOUT_CHANGE = 3
WEBDRIVER_TIMEOUT = 20 # Default timeout for waits

# --- Helper Functions for URL Scraping ---

def safe_get(driver, url):
    """Safely navigates the driver to a URL, handling WebDriver exceptions."""
    try:
        driver.get(url)
        return True
    except WebDriverException as e:
        logging.error(f"Error navigating to {url}: {e}")
        return False

def scroll_page(driver):
    """Scrolls down the page to load dynamic content."""
    last_height = driver.execute_script("return document.body.scrollHeight")
    scroll_attempts_no_change = 0
    while True:
        try:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(SCROLL_PAUSE_TIME)
            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                scroll_attempts_no_change += 1
                logging.info(f"Scroll height unchanged attempt {scroll_attempts_no_change}/{MAX_SCROLL_ATTEMPTS_WITHOUT_CHANGE}")
                if scroll_attempts_no_change >= MAX_SCROLL_ATTEMPTS_WITHOUT_CHANGE:
                    logging.info("Max scroll attempts reached.")
                    break
            else:
                scroll_attempts_no_change = 0
            last_height = new_height
        except WebDriverException as e:
            logging.warning(f"Error during scrolling: {e}")
            # Optional: Add checks to see if driver is still responsive
            break # Break loop on error during scroll

# --- Functions to Scrape Match URLs ---

def scrape_live_matches(driver):
    """Scrapes URLs for live/upcoming matches from the fixtures page."""
    live_matches = []
    processed_urls = set() # Avoid duplicates

    logging.info(f"Attempting to scrape live matches from: {FIXTURES_URL}")
    if not safe_get(driver, FIXTURES_URL):
        return []

    try:
        # Wait for a general match item indicator to be present
        WebDriverWait(driver, WEBDRIVER_TIMEOUT).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "a[href*='/match/']"))
        )
        logging.info("Fixtures page potentially loaded. Starting scroll...")
        scroll_page(driver)
        logging.info("Scrolling finished. Parsing page source for live matches.")

        soup = BeautifulSoup(driver.page_source, 'lxml') # Use lxml parser
        match_link_tags = soup.find_all('a', href=re.compile(r'/match/\d+/\d+'))
        logging.info(f"Found {len(match_link_tags)} potential match links on fixtures page.")

        for link_tag in match_link_tags:
            match_url = link_tag.get('href')
            if not match_url:
                continue

            absolute_url = urljoin(BASE_URL, match_url)
            if absolute_url in processed_urls:
                continue

            # --- !! VERIFY LIVE DETECTION LOGIC !! ---
            # This logic needs updating based on how iplt20.com currently marks live matches
            is_live = False
            # Example: Check parent container for a specific "live" class or text
            parent_container = link_tag.find_parent(class_=re.compile(r'(live|status--live)', re.IGNORECASE))
            if parent_container:
                 # Further check if it truly indicates live (might need more specific class/text)
                 if "live" in parent_container.get('class', []) or "live" in str(parent_container.text).lower():
                      is_live = True
                      logging.info(f"Potential live indicator found for: {absolute_url}")
            # --- END LIVE DETECTION LOGIC ---

            if is_live:
                live_matches.append(absolute_url)
                logging.info(f"Added Live/Upcoming Match: {absolute_url}")

            processed_urls.add(absolute_url)

    except TimeoutException:
        logging.error("Timeout waiting for fixtures page elements.")
    except Exception as e:
        logging.error(f"Unexpected error scraping live matches: {e}", exc_info=True)

    logging.info(f"Finished scraping fixtures. Found {len(live_matches)} live/upcoming matches.")
    return live_matches

def scrape_past_matches(driver):
    """Scrapes URLs for past matches from the results page."""
    past_matches_urls = set()
    logging.info(f"Attempting to scrape past matches from: {RESULTS_URL}")
    if not safe_get(driver, RESULTS_URL):
        return []

    try:
        # Wait for a general match item indicator
        WebDriverWait(driver, WEBDRIVER_TIMEOUT).until(
             EC.presence_of_element_located((By.CSS_SELECTOR, "a[href*='/match/']"))
        )
        logging.info("Results page potentially loaded. Starting scroll...")
        scroll_page(driver)
        logging.info("Scrolling finished. Parsing page source for past matches.")

        soup = BeautifulSoup(driver.page_source, 'lxml')
        # --- !! VERIFY SELECTOR for PAST MATCHES !! ---
        # Find all relevant links, potentially within a specific container
        # search_area = soup.find('div', id='smResultsWidget') # Example old container ID
        # match_link_tags = search_area.find_all(...) if search_area else soup.find_all(...)
        match_link_tags = soup.find_all('a', href=re.compile(r'/match/\d+/\d+')) # General fallback
        # --- END SELECTOR VERIFICATION ---
        logging.info(f"Found {len(match_link_tags)} potential past match links on results page.")

        for link_tag in match_link_tags:
            match_url = link_tag.get('href')
            if not match_url:
                continue
            absolute_url = urljoin(BASE_URL, match_url)
            # Add extra checks if needed to filter out non-result links if the selector is too broad
            past_matches_urls.add(absolute_url)

    except TimeoutException:
        logging.error("Timeout waiting for results page elements.")
    except Exception as e:
        logging.error(f"Unexpected error scraping past matches: {e}", exc_info=True)

    logging.info(f"Finished scraping results. Found {len(past_matches_urls)} unique past match URLs.")
    return list(past_matches_urls)


# --- Functions to Scrape Ball-by-Ball Commentary ---

def parse_commentary_from_soup(soup, commentary_event_selector, over_selector, run_selector, start_text_selector, text_selector):
    """
    Helper function to parse commentary from a BeautifulSoup soup object.
    Returns a list of commentary strings found in the soup, oldest first.
    Selectors MUST be verified against the current website.
    """
    parsed_entries = []
    logging.info(f"Parsing soup using event selector: '{commentary_event_selector}'")

    # Use select for CSS selectors
    all_commentary_elements = soup.select(commentary_event_selector)
    logging.info(f"Found {len(all_commentary_elements)} potential commentary elements in current view.")

    if not all_commentary_elements:
        logging.warning(f"Could not find elements using selector '{commentary_event_selector}' in the current view.")
        logging.warning("=> Ensure the selector correctly targets commentary items for the ACTIVE inning. <=")
        return [] # Return empty list if no elements found

    for element in all_commentary_elements:
        try:
            # Use select_one which returns None if not found, simplifying checks
            cmd_over_element = element.select_one(over_selector)
            ov_run_element = element.select_one(run_selector)
            start_text_element = element.select_one(start_text_selector)
            text_element = element.select_one(text_selector)

            # Extract text safely
            cmd_over_text = cmd_over_element.get_text(strip=True) if cmd_over_element else ""
            ov_run_text = ov_run_element.get_text(strip=True) if ov_run_element else ""
            commentary_start_text = start_text_element.get_text(strip=True) if start_text_element else ""
            commentary_text = text_element.get_text(strip=True) if text_element else ""

            # Combine only if commentary text exists
            if commentary_text:
                # Basic cleaning - may need refinement based on actual output
                if cmd_over_text and "(" not in cmd_over_text: # Avoid adding empty parens if ov_run is empty
                     over_info = f"{cmd_over_text} ({ov_run_text})"
                elif cmd_over_text:
                     over_info = cmd_over_text # Assume run is included if parens exist
                else:
                     over_info = ov_run_text # Fallback to just run info

                # Combine parts, handling potentially empty start_text
                parts = [over_info, commentary_start_text, commentary_text]
                full_entry_text = " - ".join(p for p in parts if p) # Join non-empty parts with hyphen

                # Remove leading/trailing hyphens/spaces that might result from empty parts
                full_entry_text = full_entry_text.strip(" - ")

                if len(full_entry_text) > 5: # Basic check for meaningful content
                    parsed_entries.append(full_entry_text)

        except Exception as parse_err:
            logging.warning(f"Error parsing a single commentary element: {parse_err}", exc_info=False)
            continue

    # The website usually displays commentary newest first.
    # Reverse the list so the oldest is first, latest is last.
    return parsed_entries[::-1]


def scrape_match_commentary(driver, url):
    """
    Fetches commentary from a specific IPL match URL.
    Handles clickable tabs for innings (attempts first defined number).
    Returns a list of commentary strings for the FIRST successfully processed inning.
    NOTE: Selectors are likely outdated and NEED VERIFICATION/UPDATING.
    """
    commentary_data = [] # Store commentary for the first processed inning
    wait = WebDriverWait(driver, 20) # Wait time for elements

    # --- !! VERIFY THESE SELECTORS AGAINST CURRENT iplt20.com !! ---
    # These are crucial and WILL likely need updating. Inspect the match page source.
    innings_tab_selector = ".ap-inner-tb-click" # Example: Class for clickable innings tabs
    active_commentary_container_selector = "div.commentary-event-listing" # Example: Container with commentary items
    commentary_event_selector = "div.cmdEvent" # Example: Selector for individual ball commentary blocks/items
    over_selector = ".cmdOver" # Example: Selector for Over.Ball info within an item
    run_selector = ".ovRun" # Example: Selector for runs/event (W, 4, 6, etc.) within an item
    start_text_selector = ".commentaryStartText" # Example: Selector for Bowler to Batsman text within an item
    text_selector = ".commentaryText" # Example: Selector for the main commentary description within an item
    # --- END SELECTOR VERIFICATION ---

    try:
        logging.info(f"Navigating to match commentary URL: {url}")
        if not safe_get(driver, url): # Use safe_get helper
            return []

        logging.info(f"Waiting for potential innings tabs (selector: '{innings_tab_selector}') or commentary container ('{active_commentary_container_selector}')")
        try:
            # Wait for EITHER the tabs OR the container to be present
            wait.until(EC.presence_of_element_located(
                (By.CSS_SELECTOR, f"{innings_tab_selector}, {active_commentary_container_selector}")
            ))
            # Find tabs AFTER waiting
            innings_tabs = driver.find_elements(By.CSS_SELECTOR, innings_tab_selector)
            logging.info(f"Found {len(innings_tabs)} potential innings tabs.")
        except TimeoutException:
            logging.warning(f"Timeout waiting for innings tabs or commentary container. Assuming single inning page or structure change.")
            innings_tabs = [] # Proceed assuming no tabs / direct content
        except NoSuchElementException: # Should be caught by presence_of_element_located, but belt-and-suspenders
             logging.warning(f"Could not find innings tabs or commentary container. Proceeding.")
             innings_tabs = []


        num_innings_to_process = 1 # Process only the first inning/tab found for simplicity

        for inning_index in range(num_innings_to_process):
            inning_num = inning_index + 1
            logging.info(f"Attempting to process Inning {inning_num}...")

            try:
                # If tabs exist, click the target one (0-indexed)
                if innings_tabs and inning_index < len(innings_tabs):
                    # Re-find tabs to avoid staleness
                    current_tabs = driver.find_elements(By.CSS_SELECTOR, innings_tab_selector)
                    if inning_index >= len(current_tabs):
                         logging.error(f"Tab index {inning_index} out of bounds. Cannot click.")
                         break # Stop processing innings if tab isn't found
                    tab_element = current_tabs[inning_index]
                    tab_text = tab_element.text.strip() if tab_element.text else f"Tab {inning_num}"
                    logging.info(f"Clicking tab for Inning {inning_num} ('{tab_text}')")
                    try:
                         # Ensure tab is clickable before clicking
                         clickable_tab = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, innings_tab_selector))) # Wait for *a* clickable tab, assuming first one
                         # Consider refining selector if multiple tabs match early
                         if inning_index < len(current_tabs): # Double check index
                              current_tabs[inning_index].click() # Click the specific tab again
                              logging.info(f"Clicked tab {inning_num}. Waiting for content update...")
                              # Wait for the container to be present *after* the click
                              wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, active_commentary_container_selector)))
                              time.sleep(1.5) # Small static wait for JS rendering (can be unreliable)
                         else:
                              logging.error(f"Tab index {inning_index} invalid after re-find.")
                              break


                    except (ElementClickInterceptedException, StaleElementReferenceException, TimeoutException) as click_err:
                        logging.error(f"Error clicking tab or waiting for content for Inning {inning_num}: {click_err}")
                        # If click fails, attempt to parse current view anyway
                else:
                     logging.info(f"No tabs found or processing first tab view. Waiting for default content...")
                     # Wait for commentary container if no tabs were clicked or needed
                     wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, active_commentary_container_selector)))


                logging.info(f"Getting page source for Inning {inning_num}...")
                current_page_source = driver.page_source
                soup = BeautifulSoup(current_page_source, 'html.parser') # Use standard html parser

                # Parse using the helper function and verified selectors
                inning_commentary = parse_commentary_from_soup(
                    soup, commentary_event_selector, over_selector, run_selector, start_text_selector, text_selector
                )
                # Store only the first processed inning's commentary
                commentary_data = inning_commentary
                logging.info(f"Extracted {len(inning_commentary)} entries for Inning {inning_num}.")
                break # Exit loop after successfully processing the first inning

            except Exception as inning_err:
                logging.error(f"An error occurred while processing Inning {inning_num}: {inning_err}", exc_info=True)
                continue # Skip this inning if error occurs (though loop is likely 1)

        logging.info("Finished processing commentary section.")

    except TimeoutException as e:
        logging.error(f"Initial Page load or element wait timeout occurred for URL {url}: {e}")
        return [] # Return empty list on error
    except WebDriverException as e:
        logging.error(f"WebDriver error occurred: {e}")
        return []
    except Exception as e:
        logging.error(f"An unexpected error occurred during commentary scraping setup for {url}: {e}", exc_info=True)
        return []

    # Returns a list of strings, oldest commentary first, latest last
    return commentary_data