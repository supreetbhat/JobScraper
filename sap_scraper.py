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
    raise ValueError("Missing Telegram secrets. Check your .env file.")

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
    """Fires a message to Telegram and returns the message ID for threading."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID, 
        "text": message, 
        "parse_mode": "HTML", 
        "disable_web_page_preview": True
    }
    
    # If a previous message ID is provided, reply to it to create a thread
    if reply_to:
        payload["reply_to_message_id"] = reply_to
        
    try:
        response = requests.post(url, json=payload).json()
        if response.get("ok"):
            return response["result"]["message_id"]
        else:
            print(f"Telegram API Error: {response}")
            return None
    except Exception as e:
        print(f"Failed to send Telegram message: {e}")
        return None

def get_previously_seen_jobs():
    if not os.path.exists(SEEN_FILE):
        return set()
    with open(SEEN_FILE, "r") as file:
        return set(file.read().splitlines())

def save_new_jobs(new_links):
    with open(SEEN_FILE, "a") as file:
        for link in new_links:
            file.write(link + "\n")

def calculate_priority(company, title):
    score = 0
    t_low = title.lower()
    c_low = company.lower()
    
    if any(word in t_low for word in BLACKLIST): return -100 
    if any(top.lower() in c_low for top in TOP_COMPANIES): score += 30 
    
    for tech in TECH_STACK:
        if tech in t_low: score += 10 
        
    if any(word in t_low for word in ["data science", "machine learning", "analytics", "ai", "llm", "engineer", "dataops"]):
        score += 15
        
    return score

def dork_for_ats_link(company, title):
    ats_domains = [
        "site:myworkdayjobs.com", "site:personio.de", "site:personio.com", 
        "site:join.com", "site:ashbyhq.com", "site:smartrecruiters.com", 
        "site:softgarden.io", "site:greenhouse.io", "site:lever.co"
    ]
    
    ats_footprints = " OR ".join(ats_domains)
    query = f'{company} {title} "English" ({ats_footprints})'
    
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=3))
            for res in results:
                href = res.get('href', '').lower()
                clean_c = company.lower().split()[0]
                
                if any(ats.replace("site:", "") in href for ats in ats_domains):
                    if clean_c in href.replace("-", "").replace("_", ""):
                        return res.get('href')
                        
        time.sleep(random.uniform(2.5, 4.5))
    except Exception as e:
        pass
    return None

# --- MAIN EXECUTION ---
def scrape_all():
    options = Options()
    
    # ---> COMMENTED OUT FOR LOCAL VISUAL TESTING <---
    # options.add_argument('--headless')
    # options.add_argument('--disable-gpu')
    
    options.add_argument('--window-size=1920,1080')
    options.add_argument('user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36')
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    
    previously_seen = get_previously_seen_jobs()
    new_links_to_save = []
    job_payloads = [] # Stores dicts with {score, company, title, link, source}
    
    print("Initiating Unified Master Scraper Sequence...")
    
    # 1. SCRAPE THE DAX 40 DIRECT PORTALS
    for company, urls in COMPANY_URLS.items():
        print(f"Infiltrating Direct Portal: {company}...")
        for url in urls:
            try:
                driver.get(url)
                time.sleep(8) # 8 seconds for heavy enterprise JS rendering
                
                all_links = driver.execute_script(SHADOW_JS)
                
                for link_data in all_links:
                    text = str(link_data.get('text', '')).strip().replace('\n', ' ')
                    href = str(link_data.get('href', '')).strip()
                    
                    if not href or href.startswith('javascript:') or href in previously_seen or href in new_links_to_save:
                        continue
                        
                    title_lower = text.lower()
                    score = calculate_priority(company, text)
                    
                    is_student = any(word in title_lower for word in ["student", "intern", "werkstudent", "thesis", "praktikum"])
                    
                    if is_student and len(text) > 8 and score > 0:
                        new_links_to_save.append(href)
                        job_payloads.append({"score": score, "company": company, "title": text, "link": href, "source": "Direct"})
                        
            except Exception as e:
                print(f"Warning: {company} defenses held up. Moving on.")
                continue 

    # 2. SCRAPE JOB BOARDS (Last 24 Hours Only)
    board_sources = [
        {
            "name": "LinkedIn",
            "url": 'https://www.linkedin.com/jobs/search/?keywords=("working student" OR "Werkstudent" OR "intern") AND ("data science" OR "AI" OR "machine learning")&location=Germany&f_TPR=r86400&sortBy=DD',
            "card_tag": "div", "card_class": "base-search-card__info",
            "title_tag": "h3", "company_tag": "h4"
        },
        {
            "name": "StepStone",
            "url": 'https://www.stepstone.de/jobs/working-student-data-science?it=1',
            "card_tag": "article"
        }
    ]

    for source in board_sources:
        print(f"Infiltrating Board: {source['name']}...")
        try:
            driver.get(source['url'])
            time.sleep(5)
            
            # Scroll to load lazy items
            for _ in range(3):
                driver.find_element(By.TAG_NAME, 'body').send_keys('\ue010') # Page Down key
                time.sleep(2)
                
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            
            if source['name'] == "StepStone":
                cards = soup.find_all(source['card_tag'], attrs={"data-at": "job-item"})
            else:
                cards = soup.find_all(source['card_tag'], class_=source['card_class'])
            
            for card in cards:
                try:
                    title = card.find(source['title_tag']).text.strip() if source['name'] == 'LinkedIn' else card.find('h2').text.strip()
                    
                    company_elem = card.find('span', attrs={"data-at": "job-item-company-name"}) if source['name'] == "StepStone" else card.find(source['company_tag'])
                    company = company_elem.text.strip() if company_elem else "Unknown"
                    
                    # We need the href from the card. Stepstone keeps it in the article tag or an anchor inside.
                    a_tag = card.find('a')
                    href = a_tag['href'] if a_tag else ""
                    
                    # Fix relative links
                    if href.startswith('/'):
                        href = "https://www.stepstone.de" + href if source['name'] == "StepStone" else href
                    
                    if not href or href in previously_seen or href in new_links_to_save:
                        continue
                        
                    if any(role in title.lower() for role in ["working student", "werkstudent", "intern"]):
                        score = calculate_priority(company, title)
                        if score > 15: # Stricter threshold for job boards to kill noise
                            
                            print(f"High value target found on {source['name']}: {company}. Hunting ATS link...")
                            ats_link = dork_for_ats_link(company, title)
                            final_link = ats_link if ats_link else href
                            
                            new_links_to_save.append(href) # Save original to prevent re-scraping
                            job_payloads.append({"score": score, "company": company, "title": title, "link": final_link, "source": source['name']})
                except Exception:
                    continue
                    
        except Exception as e:
            print(f"Skipping {source['name']} due to error.")

    driver.quit()
    
    # 3. SORT AND DISPATCH (WITH THREADED CHUNKING)
    if job_payloads:
        # Sort by score descending
        job_payloads.sort(key=lambda x: x['score'], reverse=True)
        
        MAX_LEN = 3900 # Safe buffer below Telegram's 4096 limit
        current_chunk = "🚨 <b>Elite Data/AI Roles Detected (Last 24h):</b>\n\n"
        last_message_id = None
        
        for job in job_payloads:
            fire = "🔥" if job['score'] >= 45 else "⭐"
            src_tag = f"[{job['source']}]" if job['source'] != "Direct" else "[DAX40]"
            
            line = f"{fire} <b>{job['company']}</b> [Score: {job['score']}]\n{src_tag} <a href='{job['link']}'>{job['title']}</a>\n\n"
            
            # If adding this job pushes us over the limit, send the current chunk now
            if len(current_chunk) + len(line) > MAX_LEN:
                last_message_id = send_telegram_alert(current_chunk, reply_to=last_message_id)
                current_chunk = line # Start the next chunk with the current job
                time.sleep(1.5) # Be nice to Telegram's rate limits
            else:
                current_chunk += line
                
        # Send whatever jobs are left in the final chunk
        if current_chunk.strip():
            send_telegram_alert(current_chunk, reply_to=last_message_id)
            
        save_new_jobs(new_links_to_save)
        print(f"Success. Pushed {len(job_payloads)} elite jobs to Telegram across a threaded message.")
    else:
        print("No new high-priority roles today.")

if __name__ == "__main__":
    scrape_all()