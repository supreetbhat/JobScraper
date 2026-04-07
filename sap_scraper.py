import time
import requests
import os
import random
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from duckduckgo_search import DDGS
from duckduckgo_search.exceptions import DuckDuckGoSearchException

# --- SECURE CLOUD CONFIGURATION ---
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

if not TELEGRAM_TOKEN or not CHAT_ID:
    # On GitHub, this will crash if Secrets aren't set correctly
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
    "business development", "operations", "datenanalyst", "entwickler", "künstliche intelligenz"
]

TECH_STACK = [
    "python", "sql", "pyspark", "databricks", "powerbi", "dax", "aws", "azure", 
    "docker", "kubernetes", "llm", "rag", "langchain", "nlp", "claude", "gpt",
    "fastapi", "react", "typescript", "pandas", "numpy"
]

# --- DIRECT DAX 40 PORTALS ---
COMPANY_URLS = {
    "SAP": ["https://jobs.sap.com/search/?q=Data&locationsearch=Germany&optionsFacetsDD_customfield3=Student", "https://jobs.sap.com/search/?q=AI&locationsearch=Germany&optionsFacetsDD_customfield3=Student"],
    "Siemens": ["https://jobs.siemens.com/careers?query=Werkstudent+data+science&location=Germany"],
    "Infineon": ["https://jobs.infineon.com/careers?query=Werkstudent+Data+Science&location=Germany"],
    "Siemens Energy": ["https://jobs.siemens-energy.com/jobs?keywords=Werkstudent+data+science&country=Germany"],
    "Volkswagen": ["https://jobs.volkswagen-group.com/search?query=Werkstudent+Data+Science&country=DE"],
    "BMW": ["https://www.bmwgroup.jobs/de/en/jobfinder.html?q=Werkstudent+data+science"],
    "Mercedes-Benz": ["https://group.mercedes-benz.com/careers/job-search/?searchTerm=Werkstudent+data+science&country=DE"],
    "Porsche": ["https://jobs.porsche.com/index.php?ac=search_result&search[free_text]=Werkstudent+data+science&search[country]=Deutschland"],
    "Continental": ["https://conti-jobs.com/de/search/?q=Werkstudent+data+science&country=Germany"],
    "Allianz": ["https://careers.allianz.com/go/Students/5120301/?q=data+science&searchby=category&pageSize=20"],
    "Munich Re": ["https://careers.munichre.com/en/munichre/search/?q=data+science&type=Internship+%26+Working+Student&location=Germany"],
    "Deutsche Bank": ["https://careers.db.com/professionals/search-roles/#/"], 
    "Commerzbank": ["https://jobs.commerzbank.com/index.php?ac=search_result&search[free_text]=Werkstudent+data+science"],
    "Schwarz Group": ["https://jobs.schwarz/en/jobsearch?q=Werkstudent+data+science"],
    "Aldi Süd": ["https://www.aldi-sued.de/de/karriere/stellenangebote.html?q=Werkstudent+data+science"],
    "Aldi Nord": ["https://www.aldi-nord.de/karriere/stellenangebote.html"],
    "DHL": ["https://careers.dhl.com/global/en/search-results?keywords=Werkstudent+data+science&country=Germany&jobtype=Student"],
    "Edeka": ["https://verbundkarriere.edeka/stellenangebote/?q=Werkstudent+data+science"],
    "E.ON": ["https://www.eon.com/de/karriere/stellensuche.html?q=Werkstudent+data+science&type=student"],
    "BASF": ["https://basf.jobs/search/?q=Werkstudent+data+science&locationsearch=Germany"],
    "Bayer": ["https://career.bayer.com/en/search#q=Werkstudent%20data%20science&t=Jobs&sort=relevancy&layout=table&f:country=[Germany]"],
    "Merck": ["https://careers.merckgroup.com/global/en/search-results?keywords=Werkstudent+data+science&country=Germany&category=Students+%26+Graduates"]
}

# --- SHADOW DOM PIERCER ---
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
        return response["result"]["message_id"] if response.get("ok") else None
    except Exception: return None

def get_previously_seen_jobs():
    if not os.path.exists(SEEN_FILE): return set()
    with open(SEEN_FILE, "r") as file: return set(file.read().splitlines())

def save_new_jobs(new_links):
    with open(SEEN_FILE, "a") as file:
        for link in new_links: file.write(link + "\n")

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

def dork_for_ats_link(company, title):
    ats_domains = ["site:myworkdayjobs.com", "site:personio.de", "site:personio.com", "site:join.com", "site:smartrecruiters.com"]
    query = f'{company} {title} "English" ({" OR ".join(ats_domains)})'
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=3))
            for res in results:
                if any(ats.replace("site:", "") in res.get('href', '').lower() for ats in ats_domains):
                    return res.get('href')
        time.sleep(random.uniform(2, 4))
    except Exception: pass
    return None

# --- MAIN EXECUTION ---
def scrape_all():
    options = Options()
    
    # --- AUTOMATIC CLOUD FIX FOR GITHUB ACTIONS ---
    if os.getenv('GITHUB_ACTIONS') == 'true':
        print("DETECTED: GitHub Cloud Runner. Applying Sandbox fixes...")
        options.add_argument('--headless')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-gpu')
    else:
        print("DETECTED: Local MacBook. Skipping Sandbox fixes...")
        # options.add_argument('--headless') # Uncomment for invisible local run
        pass

    options.add_argument('--window-size=1920,1080')
    options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    
    previously_seen = get_previously_seen_jobs()
    new_links_to_save = []
    job_payloads = []
    
    print("Initiating Scraper Sequence...")
    
    # [SCALED BACK FOR STABILITY TEST]
    for company, urls in list(COMPANY_URLS.items()):
        print(f"Checking {company}...")
        for url in urls:
            try:
                driver.get(url)
                time.sleep(8)
                all_links = driver.execute_script(SHADOW_JS)
                for link_data in all_links:
                    text = str(link_data.get('text', '')).strip().replace('\n', ' ')
                    href = str(link_data.get('href', '')).strip()
                    if not href or href in previously_seen or href in new_links_to_save: continue
                    score = calculate_priority(company, text)
                    if score > 0 and any(w in text.lower() for w in ["student", "intern", "werkstudent"]):
                        new_links_to_save.append(href)
                        job_payloads.append({"score": score, "company": company, "title": text, "link": href, "source": "Direct"})
            except Exception: continue

    driver.quit()
    
    if job_payloads:
        job_payloads.sort(key=lambda x: x['score'], reverse=True)
        current_chunk = "🚨 <b>Elite Roles Detected:</b>\n\n"
        last_id = None
        for job in job_payloads:
            line = f"⭐ <b>{job['company']}</b> [Score: {job['score']}]\n<a href='{job['link']}'>{job['title']}</a>\n\n"
            if len(current_chunk) + len(line) > 3900:
                last_id = send_telegram_alert(current_chunk, reply_to=last_id)
                current_chunk = line
                time.sleep(1)
            else: current_chunk += line
        send_telegram_alert(current_chunk, reply_to=last_id)
        save_new_jobs(new_links_to_save)
        print(f"Sent {len(job_payloads)} jobs.")
    else:
        print("No new jobs.")

if __name__ == "__main__":
    scrape_all()