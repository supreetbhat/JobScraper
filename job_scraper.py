import time
import requests
import os
import random
import html
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from duckduckgo_search import DDGS # Reverted to standard import

# --- SECURE CLOUD CONFIGURATION ---
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

if not TELEGRAM_TOKEN or not CHAT_ID:
    raise ValueError("Missing Telegram secrets. Check GitHub Secrets or .env file.")

SEEN_FILE = "seen_jobs.txt"

# --- THE BRAINS: KEYWORDS & FILTERS ---
TOP_COMPANIES = [
    "SAP", "Siemens", "Bosch", "BMW", "Mercedes-Benz", "Volkswagen", "Porsche", "Audi", 
    "Infineon", "Airbus", "Lufthansa", "Bayer", "Merck", "BASF", "Henkel", "Allianz", 
    "Munich Re", "Deutsche Bank", "Zalando", "HelloFresh", "Delivery Hero", "DeepL", 
    "Celonis", "N26", "Trade Republic", "Check24", "Hapag-Lloyd", "DHL", "Deutsche Bahn",
    "Google", "Microsoft", "Amazon", "Apple", "Meta", "NVIDIA", "Tesla", "Stripe"
]

BLACKLIST = [
    "tax", "legal", "accounting", "event", "sales", "verkauf", "hr", "recruiter", 
    "marketing", "content", "customer", "retail", "vorgarten", "assistant", 
    "business development", "operations", "datenanalyst", "entwickler", "künstliche intelligenz",
    "unpaid", "volunteer"
]

TECH_STACK = [
    "python", "sql", "pyspark", "databricks", "powerbi", "dax", "aws", "azure", 
    "docker", "kubernetes", "llm", "rag", "langchain", "nlp", "claude", "gpt",
    "fastapi", "react", "typescript", "pandas", "numpy"
]

# Strict German words that indicate the job description is likely in German
# (Note: 'werkstudent' is allowed as it is universally used for English roles too)
GERMAN_WORDS = [
    " und ", " für ", " im ", " bereich ", " praktikant", " praktikum", 
    " entwickler", " datenanalyst", " wissenschaftlicher", " mitarbeiter", 
    " künstliche", " intelligenz", " schwerpunkt", " abteilung"
]

COMPANY_URLS = {
    "SAP": ["https://jobs.sap.com/search/?q=Data&locationsearch=Germany&optionsFacetsDD_customfield3=Student", "https://jobs.sap.com/search/?q=AI&locationsearch=Germany&optionsFacetsDD_customfield3=Student"],
    "Siemens": ["https://jobs.siemens.com/careers?query=Werkstudent+data+science&location=Germany"],
    "Infineon": ["https://jobs.infineon.com/careers?query=Werkstudent+Data+Science&location=Germany"],
    "Volkswagen": ["https://jobs.volkswagen-group.com/search?query=Werkstudent+Data+Science&country=DE"],
    "BMW": ["https://www.bmwgroup.jobs/de/en/jobfinder.html?q=Werkstudent+data+science"],
    "Allianz": ["https://careers.allianz.com/go/Students/5120301/?q=data+science&searchby=category&pageSize=20"],
    "BASF": ["https://basf.jobs/search/?q=Werkstudent+data+science&locationsearch=Germany"],
    "Bayer": ["https://career.bayer.com/en/search#q=Werkstudent%20data%20science&t=Jobs&sort=relevancy&layout=table&f:country=[Germany]"]
}

SHADOW_JS = """
function getAllLinks(root) {
    let links = Array.from(root.querySelectorAll('a'));
    let nodes = Array.from(root.querySelectorAll('*'));
    for (let node of nodes) {
        if (node.shadowRoot) {
            links = links.concat(getAllLinks(node.shadowRoot));
        }
    }
    return links;
}
return getAllLinks(document).map(a => { return {text: a.innerText || a.textContent, href: a.href}; });
"""

# --- HELPER FUNCTIONS ---
def send_telegram_alert(message, reply_to=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML", "disable_web_page_preview": True}
    if reply_to: payload["reply_to_message_id"] = reply_to
    try:
        response = requests.post(url, json=payload).json()
        if not response.get("ok"):
            print(f"!!! TELEGRAM ERROR: {response.get('description')}")
        return response["result"]["message_id"] if response.get("ok") else None
    except Exception as e: 
        print(f"Telegram Request Failed: {e}")
        return None

def get_previously_seen_jobs():
    if not os.path.exists(SEEN_FILE): return set()
    with open(SEEN_FILE, "r") as file: return set(file.read().splitlines())

def save_new_jobs(new_links):
    with open(SEEN_FILE, "a") as file:
        for link in new_links: file.write(link + "\n")

def is_english_role(title):
    """Drops jobs that have strict German grammar or titles."""
    t_low = title.lower()
    if any(word in t_low for word in GERMAN_WORDS):
        return False
    return True

def calculate_priority(company, title):
    score = 0
    t_low = title.lower()
    c_low = company.lower()
    if any(word in t_low for word in BLACKLIST): return -100 
    if any(top.lower() in c_low for top in TOP_COMPANIES): score += 30 
    for tech in TECH_STACK:
        if tech in t_low: score += 10 
    if any(word in t_low for word in ["data science", "machine learning", "analytics", "ai", "llm", "engineer"]):
        score += 15
    return score

def verify_company_legitimacy(company_name):
    """Network-free heuristic scam check."""
    c_low = company_name.lower()
    if any(top.lower() in c_low for top in TOP_COMPANIES): return True
    scam_flags = ["confidential", "stealth", "unknown", "test company", "hiring agency", "dummy"]
    if not company_name or any(flag in c_low for flag in scam_flags): return False
    return True

def scrape_wellfound_remote(previously_seen):
    """Dorks Wellfound for English remote roles."""
    print("\n--- Infiltrating Wellfound ---")
    wellfound_jobs = []
    query = 'site:wellfound.com/jobs "Data Science" "English" "Remote" ("Intern" OR "Working Student")'
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=10))
            for res in results:
                href = res.get('href', '')
                title = res.get('title', '')
                if href and href not in previously_seen and "jobs/" in href and is_english_role(title):
                    company = title.split("|")[0].strip() if "|" in title else "Startup"
                    score = calculate_priority(company, title) + 10 
                    if score > 10:
                        wellfound_jobs.append({
                            "score": score, "company": company, "title": title, 
                            "link": href, "source": "Wellfound", "location": "Remote (Global/EU)"
                        })
        time.sleep(2)
    except Exception as e: pass
    return wellfound_jobs

# --- MAIN EXECUTION ---
def scrape_all():
    options = Options()
    
    if os.getenv('GITHUB_ACTIONS') == 'true':
        print("DETECTED: GitHub Cloud Runner. Applying Sandbox fixes...")
        options.add_argument('--headless')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-gpu')
    
    options.add_argument('--window-size=1920,1080')
    options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    
    previously_seen = get_previously_seen_jobs()
    new_links_to_save = []
    
    dax_payloads = []
    remote_payloads = []
    
    print("Initiating Master Scraper Sequence...")
    
    # 1. SCRAPE DAX 40 DIRECT PORTALS
    for company, urls in COMPANY_URLS.items():
        print(f"Checking Direct: {company}...")
        for url in urls:
            try:
                driver.get(url)
                time.sleep(6)
                all_links = driver.execute_script(SHADOW_JS)
                for link_data in all_links:
                    text = str(link_data.get('text', '')).strip().replace('\n', ' ')
                    href = str(link_data.get('href', '')).strip()
                    
                    if not href or href in previously_seen or href in new_links_to_save: continue
                    if not is_english_role(text): continue # Language check
                    
                    score = calculate_priority(company, text)
                    if score > 0 and any(w in text.lower() for w in ["student", "intern", "werkstudent"]):
                        new_links_to_save.append(href)
                        dax_payloads.append({
                            "score": score, "company": company, "title": text, 
                            "link": href, "source": "Direct", "location": "Germany (Hybrid/On-site)"
                        })
            except Exception: continue

    # 2. SCRAPE REMOTE JOB BOARDS
    board_sources = [
        {
            "name": "LinkedIn Remote",
            "url": 'https://www.linkedin.com/jobs/search/?keywords=("working student" OR "Werkstudent" OR "intern") AND ("data science" OR "AI" OR "machine learning")&location=European%20Union&f_TPR=r86400&f_WT=2&sortBy=DD',
            "card_tag": "div", "card_class": "base-search-card__info",
            "title_tag": "h3", "company_tag": "h4", "loc_tag": "span", "loc_class": "job-search-card__location"
        },
        {
            "name": "StepStone Remote",
            "url": 'https://www.stepstone.de/jobs/working-student-data-science?it=1&ag=remote',
            "card_tag": "article", "loc_tag": "span", "loc_attr": {"data-at": "job-item-location"}
        }
    ]

    for source in board_sources:
        print(f"\n--- Infiltrating {source['name']} ---")
        try:
            driver.get(source['url'])
            time.sleep(5)
            for _ in range(2):
                driver.find_element(By.TAG_NAME, 'body').send_keys('\ue010')
                time.sleep(1)
                
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            cards = soup.find_all(source['card_tag'], attrs={"data-at": "job-item"}) if "StepStone" in source['name'] else soup.find_all(source['card_tag'], class_=source['card_class'])
            
            for card in cards:
                try:
                    title = card.find(source['title_tag']).text.strip() if "LinkedIn" in source['name'] else card.find('h2').text.strip()
                    
                    if not is_english_role(title): 
                        continue # Language check
                    
                    company_elem = card.find('span', attrs={"data-at": "job-item-company-name"}) if "StepStone" in source['name'] else card.find(source['company_tag'])
                    company = company_elem.text.strip() if company_elem else "Unknown"
                    
                    # Extract Location
                    if "LinkedIn" in source['name']:
                        loc_elem = card.find(source['loc_tag'], class_=source['loc_class'])
                    else:
                        loc_elem = card.find(source['loc_tag'], attrs=source['loc_attr'])
                    location = loc_elem.text.strip() if loc_elem else "Remote"
                    
                    a_tag = card.find('a')
                    href = a_tag['href'] if a_tag else ""
                    if href.startswith('/'): href = "https://www.stepstone.de" + href
                    
                    if not href or href in previously_seen or href in new_links_to_save: 
                        continue
                    
                    score = calculate_priority(company, title)
                    if score > 10 and verify_company_legitimacy(company):
                        new_links_to_save.append(href)
                        remote_payloads.append({
                            "score": score, "company": company, "title": title, 
                            "link": href, "source": source['name'], "location": location
                        })
                except Exception: pass
        except Exception: pass

    driver.quit()

    # 3. WELLFOUND DORKING
    wellfound_results = scrape_wellfound_remote(previously_seen)
    for job in wellfound_results:
        if verify_company_legitimacy(job['company']):
            remote_payloads.append(job)
            new_links_to_save.append(job['link'])

    # --- TELEGRAM DISPATCH ---
    
    # Dispatch DAX 40 Jobs
    if dax_payloads:
        dax_payloads.sort(key=lambda x: x['score'], reverse=True)
        current_chunk = "🚨 <b>Elite DAX 40 Roles:</b>\n\n"
        last_id = None
        for job in dax_payloads:
            safe_title = html.escape(job['title'])
            safe_company = html.escape(job['company'])
            safe_loc = html.escape(job['location'])
            
            line = f"🏢 <b>{safe_company}</b> [Score: {job['score']}]\n📍 {safe_loc}\n<a href='{job['link']}'>{safe_title}</a>\n\n"
            if len(current_chunk) + len(line) > 3900:
                last_id = send_telegram_alert(current_chunk, reply_to=last_id)
                current_chunk = line
                time.sleep(1)
            else: current_chunk += line
        send_telegram_alert(current_chunk, reply_to=last_id)

    # Dispatch Remote Jobs
    if remote_payloads:
        remote_payloads.sort(key=lambda x: x['score'], reverse=True)
        current_chunk = "🌍 <b>Remote Startup & Tech Roles:</b>\n\n"
        last_id = None
        for job in remote_payloads:
            safe_title = html.escape(job['title'])
            safe_company = html.escape(job['company'])
            safe_loc = html.escape(job['location'])
            
            line = f"💻 <b>{safe_company}</b> [Score: {job['score']}]\n📍 {safe_loc} | {job['source']}\n<a href='{job['link']}'>{safe_title}</a>\n\n"
            if len(current_chunk) + len(line) > 3900:
                last_id = send_telegram_alert(current_chunk, reply_to=last_id)
                current_chunk = line
                time.sleep(1)
            else: current_chunk += line
        send_telegram_alert(current_chunk, reply_to=last_id)

    if not dax_payloads and not remote_payloads:
        print("No new jobs.")

    save_new_jobs(new_links_to_save)

if __name__ == "__main__":
    scrape_all()