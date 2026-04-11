import time
import requests
import os
import html
import json
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from ddgs import DDGS

# --- SECURE CLOUD CONFIGURATION ---
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

if not TELEGRAM_TOKEN or not CHAT_ID:
    raise ValueError("Missing Telegram secrets. Check GitHub Secrets or .env file.")

SEEN_FILE = "seen_jobs.txt"
SEEN_MAX_AGE_DAYS = 60  # Prune links older than this

# ─────────────────────────────────────────────
# THE BRAINS: KEYWORDS & FILTERS
# ─────────────────────────────────────────────

TOP_COMPANIES = [
    "SAP", "Siemens", "Bosch", "BMW", "Mercedes-Benz", "Volkswagen", "Porsche", "Audi",
    "Infineon", "Airbus", "Lufthansa", "Bayer", "Merck", "BASF", "Henkel", "Allianz",
    "Munich Re", "Deutsche Bank", "Zalando", "HelloFresh", "Delivery Hero", "DeepL",
    "Celonis", "N26", "Trade Republic", "Check24", "Hapag-Lloyd", "DHL", "Deutsche Bahn",
    "Google", "Microsoft", "Amazon", "Apple", "Meta", "NVIDIA", "Tesla", "Stripe",
    "Spotify", "Klarna", "Wirecard", "Personio", "Flixbus", "Babbel", "Westwing",
    "Scalable Capital", "Taxfix", "Mambu", "Contentful", "GetYourGuide", "Auto1",
    "Adjust", "SumUp", "Enpal", "Sono Motors", "Lilium", "Volocopter",
]

# Blacklist uses PHRASE matching — won't trip on "ML Research Assistant"
BLACKLIST_PHRASES = [
    "tax advisor", "legal counsel", "accounting intern", "event manager",
    "sales intern", "hr intern", "recruiter intern", "marketing intern",
    "content writer", "customer support", "retail assistant",
    "business development intern", "unpaid intern", "volunteer position",
    "pr intern", "social media intern",
]

# Single words still blacklisted (very safe to drop)
BLACKLIST_WORDS = ["verkauf", "vorgarten", "sekretär"]

TECH_STACK = [
    "python", "sql", "pyspark", "databricks", "powerbi", "dax", "aws", "azure",
    "docker", "kubernetes", "llm", "rag", "langchain", "nlp", "claude", "gpt",
    "fastapi", "react", "typescript", "pandas", "numpy", "scikit", "tensorflow",
    "pytorch", "huggingface", "spark", "kafka", "airflow", "dbt", "snowflake",
    "bigquery", "looker", "tableau", "mlflow", "vertex", "sagemaker",
]

TARGET_ROLES = [
    "data science", "machine learning", "analytics", "ai engineer", "llm",
    "data engineer", "ml engineer", "research scientist", "computer vision",
    "nlp engineer", "backend engineer", "software engineer", "applied scientist",
]

WERKSTUDENT_KEYWORDS = ["werkstudent", "working student", "intern", "praktikum", "praktikant", "student assistant"]

GERMAN_INDICATORS = [
    " und ", " für ", " im ", " bereich ", " wissenschaftlicher",
    " mitarbeiter", " schwerpunkt", " abteilung", " kenntnisse",
]

# ─────────────────────────────────────────────
# DIRECT COMPANY PORTALS (expanded to 20+)
# ─────────────────────────────────────────────

COMPANY_URLS = {
    "SAP": [
        "https://jobs.sap.com/search/?q=Data&locationsearch=Germany&optionsFacetsDD_customfield3=Student",
        "https://jobs.sap.com/search/?q=AI&locationsearch=Germany&optionsFacetsDD_customfield3=Student",
        "https://jobs.sap.com/search/?q=Machine+Learning&locationsearch=Germany&optionsFacetsDD_customfield3=Student",
    ],
    "Siemens": [
        "https://jobs.siemens.com/careers?query=Werkstudent+data+science&location=Germany",
        "https://jobs.siemens.com/careers?query=Working+Student+AI&location=Germany",
    ],
    "Infineon": ["https://jobs.infineon.com/careers?query=Werkstudent+Data+Science&location=Germany"],
    "Volkswagen": ["https://jobs.volkswagen-group.com/search?query=Werkstudent+Data+Science&country=DE"],
    "BMW": ["https://www.bmwgroup.jobs/de/en/jobfinder.html?q=Werkstudent+data+science"],
    "Allianz": ["https://careers.allianz.com/go/Students/5120301/?q=data+science&searchby=category&pageSize=20"],
    "BASF": ["https://basf.jobs/search/?q=Werkstudent+data+science&locationsearch=Germany"],
    "Bayer": ["https://career.bayer.com/en/search#q=Werkstudent%20data%20science&t=Jobs&sort=relevancy&layout=table&f:country=[Germany]"],
    "Bosch": [
        "https://jobs.bosch.com/jobs/?query=working+student+data+science&country=DE",
        "https://jobs.bosch.com/jobs/?query=working+student+machine+learning&country=DE",
    ],
    "Deutsche Bank": ["https://careers.db.com/professionals/search-roles/#/professional/results?query=working+student+data&country=Germany"],
    "Zalando": ["https://jobs.zalando.com/en/jobs/?query=working+student+data"],
    "DeepL": ["https://jobs.deepl.com/l/en"],
    "Celonis": ["https://www.celonis.com/careers/jobs/?search=data+intern"],
    "N26": ["https://n26.com/en-eu/careers#jobs?search=data"],
    "Trade Republic": ["https://traderepublic.com/careers#jobs"],
    "Personio": ["https://www.personio.com/about-personio/careers/#open-positions"],
    "GetYourGuide": ["https://careers.getyourguide.com/jobs?department=Engineering&query=data"],
    "Klarna": ["https://jobs.lever.co/klarna?team=Engineering"],
    "Spotify": ["https://www.lifeatspotify.com/jobs?l=germany&c=data"],
    "Airbus": ["https://ag.wd3.myworkdayjobs.com/Airbus/jobs?q=working+student+data"],
    "Merck": ["https://jobs.merckgroup.com/en/search#q=working+student+data&t=Jobs&layout=table&f:country=[Germany]"],
}

# ─────────────────────────────────────────────
# SHADOW DOM JS
# ─────────────────────────────────────────────

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

# ─────────────────────────────────────────────
# SCRAPER STATS (for health report)
# ─────────────────────────────────────────────

stats = {
    "sources_checked": 0,
    "sources_failed": 0,
    "raw_jobs_seen": 0,
    "new_jobs_found": 0,
    "start_time": datetime.now(),
}

# ─────────────────────────────────────────────
# HELPER FUNCTIONS
# ─────────────────────────────────────────────

def send_telegram_alert(message, reply_to=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if reply_to:
        payload["reply_to_message_id"] = reply_to
    try:
        response = requests.post(url, json=payload, timeout=10).json()
        if not response.get("ok"):
            print(f"!!! TELEGRAM ERROR: {response.get('description')}")
        return response["result"]["message_id"] if response.get("ok") else None
    except Exception as e:
        print(f"Telegram Request Failed: {e}")
        return None


def get_previously_seen_jobs():
    """Load seen jobs, pruning entries older than SEEN_MAX_AGE_DAYS."""
    if not os.path.exists(SEEN_FILE):
        return set()
    cutoff = datetime.now() - timedelta(days=SEEN_MAX_AGE_DAYS)
    valid_links = set()
    try:
        with open(SEEN_FILE, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                # Format: "URL|||TIMESTAMP" or legacy plain URL
                if "|||" in line:
                    url, ts_str = line.rsplit("|||", 1)
                    try:
                        ts = datetime.fromisoformat(ts_str)
                        if ts > cutoff:
                            valid_links.add(url.strip())
                    except ValueError:
                        valid_links.add(url.strip())
                else:
                    valid_links.add(line)
    except Exception as e:
        print(f"Error reading seen file: {e}")
    print(f"Loaded {len(valid_links)} previously seen jobs (after pruning old entries).")
    return valid_links


def save_new_jobs(new_links):
    """Save new links with timestamps."""
    ts = datetime.now().isoformat()
    with open(SEEN_FILE, "a") as f:
        for link in new_links:
            f.write(f"{link}|||{ts}\n")


def is_german_role(title):
    """Returns True if the title appears to be in German."""
    t_low = title.lower()
    return any(word in t_low for word in GERMAN_INDICATORS)


def is_werkstudent_role(title):
    t_low = title.lower()
    return any(w in t_low for w in WERKSTUDENT_KEYWORDS)


def calculate_priority(company, title, is_german=False):
    """
    Scoring guide:
      +30  — Top company match
      +15  — Core target role keyword
      +10  — Each tech stack keyword (capped at 40)
      -5   — German-language role (still shown, tagged [DE])
      -100 — Blacklisted phrase → dropped entirely
    """
    score = 0
    t_low = title.lower()
    c_low = company.lower()

    # Hard blacklist: phrases
    if any(phrase in t_low for phrase in BLACKLIST_PHRASES):
        return -100
    # Hard blacklist: single words
    if any(word in t_low for word in BLACKLIST_WORDS):
        return -100

    if any(top.lower() in c_low for top in TOP_COMPANIES):
        score += 30

    if any(role in t_low for role in TARGET_ROLES):
        score += 15

    tech_hits = sum(1 for tech in TECH_STACK if tech in t_low)
    score += min(tech_hits * 10, 40)

    if is_german:
        score -= 5  # Slight penalty but still shown

    return score


def verify_company_legitimacy(company_name):
    if not company_name:
        return False
    c_low = company_name.lower()
    if any(top.lower() in c_low for top in TOP_COMPANIES):
        return True
    scam_flags = ["confidential", "stealth", "unknown", "test company", "hiring agency", "dummy", "anonymous"]
    if any(flag in c_low for flag in scam_flags):
        return False
    return True


def safe_get(driver, url, wait=4, retries=2):
    """Load a URL with retry logic."""
    for attempt in range(retries):
        try:
            driver.get(url)
            time.sleep(wait)
            return True
        except Exception as e:
            print(f"  Attempt {attempt+1} failed for {url}: {e}")
            time.sleep(3)
    return False


# ─────────────────────────────────────────────
# SCRAPER MODULES
# ─────────────────────────────────────────────

def scrape_direct_portals(driver, previously_seen, new_links_to_save, dax_payloads):
    print("\n═══ PHASE 1: Direct Company Portals ═══")
    for company, urls in COMPANY_URLS.items():
        print(f"  → {company}...")
        stats["sources_checked"] += 1
        for url in urls:
            if not safe_get(driver, url, wait=4):
                print(f"    ✗ Timed out: {company}")
                stats["sources_failed"] += 1
                continue
            try:
                all_links = driver.execute_script(SHADOW_JS)
                for link_data in all_links:
                    text = str(link_data.get("text", "")).strip().replace("\n", " ")
                    href = str(link_data.get("href", "")).strip()

                    if not href or href in previously_seen or href in new_links_to_save:
                        continue
                    if len(text) < 5:
                        continue

                    stats["raw_jobs_seen"] += 1
                    german = is_german_role(text)
                    score = calculate_priority(company, text, is_german=german)

                    if score > 0 and is_werkstudent_role(text):
                        new_links_to_save.append(href)
                        previously_seen.add(href)
                        stats["new_jobs_found"] += 1
                        dax_payloads.append({
                            "score": score,
                            "company": company,
                            "title": text,
                            "link": href,
                            "source": "Direct Portal",
                            "location": "Germany",
                            "language": "DE" if german else "EN",
                        })
            except Exception as e:
                print(f"    ✗ Script error on {company}: {e}")


def scrape_job_boards(driver, previously_seen, new_links_to_save, remote_payloads):
    print("\n═══ PHASE 2: Job Boards ═══")

    board_sources = [
        {
            "name": "LinkedIn Remote",
            "url": (
                "https://www.linkedin.com/jobs/search/"
                '?keywords=("working student" OR "Werkstudent" OR "intern") '
                'AND ("data science" OR "AI" OR "machine learning")'
                "&location=European%20Union&f_TPR=r86400&f_WT=2&sortBy=DD"
            ),
            "parser": "linkedin",
        },
        {
            "name": "StepStone",
            "url": "https://www.stepstone.de/jobs/working-student-data-science?it=1&ag=remote",
            "parser": "stepstone",
        },
        {
            "name": "StepStone AI",
            "url": "https://www.stepstone.de/jobs/working-student-artificial-intelligence?it=1",
            "parser": "stepstone",
        },
        {
            "name": "Indeed Germany",
            "url": "https://de.indeed.com/jobs?q=working+student+data+science&l=Germany&sort=date",
            "parser": "indeed",
        },
        {
            "name": "Indeed Remote",
            "url": "https://de.indeed.com/jobs?q=working+student+data+science&l=Remote&sort=date",
            "parser": "indeed",
        },
        {
            "name": "Glassdoor",
            "url": "https://www.glassdoor.com/Job/germany-working-student-data-science-jobs-SRCH_IL.0,7_IN96_KO8,36.htm",
            "parser": "glassdoor",
        },
    ]

    for source in board_sources:
        print(f"  → {source['name']}...")
        stats["sources_checked"] += 1

        if not safe_get(driver, source["url"], wait=5):
            print(f"    ✗ Timed out: {source['name']}")
            stats["sources_failed"] += 1
            continue

        try:
            # Scroll to trigger lazy loading
            for _ in range(3):
                driver.find_element(By.TAG_NAME, "body").send_keys("\ue010")
                time.sleep(0.8)

            soup = BeautifulSoup(driver.page_source, "html.parser")
            jobs = parse_board(soup, source["parser"], source["name"])
            print(f"    Raw cards: {len(jobs)}")

            for job in jobs:
                stats["raw_jobs_seen"] += 1
                href = job.get("link", "")
                title = job.get("title", "")
                company = job.get("company", "Unknown")
                location = job.get("location", "Remote")

                if not href or href in previously_seen or href in new_links_to_save:
                    continue
                if not is_werkstudent_role(title):
                    continue

                german = is_german_role(title)
                score = calculate_priority(company, title, is_german=german)

                if score > 5 and verify_company_legitimacy(company):
                    print(f"    ✅ {company} — {title[:60]}")
                    new_links_to_save.append(href)
                    previously_seen.add(href)
                    stats["new_jobs_found"] += 1
                    remote_payloads.append({
                        "score": score,
                        "company": company,
                        "title": title,
                        "link": href,
                        "source": source["name"],
                        "location": location,
                        "language": "DE" if german else "EN",
                    })
        except Exception as e:
            print(f"    ✗ CRASH in {source['name']}: {e}")
            stats["sources_failed"] += 1


def parse_board(soup, parser, source_name):
    """Unified parser for different job board HTML structures."""
    jobs = []

    if parser == "linkedin":
        cards = soup.find_all("div", class_="base-search-card__info")
        for card in cards:
            try:
                title = card.find("h3").text.strip()
                company = card.find("h4").text.strip()
                loc = card.find("span", class_="job-search-card__location")
                location = loc.text.strip() if loc else "EU Remote"
                a = card.find_previous("a")
                href = a["href"].split("?")[0] if a else ""
                jobs.append({"title": title, "company": company, "location": location, "link": href})
            except Exception:
                continue

    elif parser == "stepstone":
        cards = soup.find_all("article", attrs={"data-at": "job-item"})
        for card in cards:
            try:
                title_el = card.find("h2")
                title = title_el.text.strip() if title_el else ""
                company_el = card.find("span", attrs={"data-at": "job-item-company-name"})
                company = company_el.text.strip() if company_el else "Unknown"
                loc_el = card.find("span", attrs={"data-at": "job-item-location"})
                location = loc_el.text.strip() if loc_el else "Germany"
                a = card.find("a")
                href = "https://www.stepstone.de" + a["href"] if a and a["href"].startswith("/") else (a["href"] if a else "")
                jobs.append({"title": title, "company": company, "location": location, "link": href})
            except Exception:
                continue

    elif parser == "indeed":
        cards = soup.find_all("div", class_="job_seen_beacon")
        for card in cards:
            try:
                title_el = card.find("h2", class_="jobTitle")
                title = title_el.text.strip() if title_el else ""
                company_el = card.find("span", class_="companyName")
                company = company_el.text.strip() if company_el else "Unknown"
                loc_el = card.find("div", class_="companyLocation")
                location = loc_el.text.strip() if loc_el else "Germany"
                a = card.find("a", href=True)
                href = "https://de.indeed.com" + a["href"] if a and a["href"].startswith("/") else (a["href"] if a else "")
                jobs.append({"title": title, "company": company, "location": location, "link": href})
            except Exception:
                continue

    elif parser == "glassdoor":
        cards = soup.find_all("li", class_="react-job-listing")
        for card in cards:
            try:
                title_el = card.find("a", class_="jobLink")
                title = title_el.text.strip() if title_el else ""
                company_el = card.find("div", class_="jobEmpolyerName")
                company = company_el.text.strip() if company_el else "Unknown"
                loc_el = card.find("span", class_="subtle")
                location = loc_el.text.strip() if loc_el else "Germany"
                href = "https://www.glassdoor.com" + title_el["href"] if title_el else ""
                jobs.append({"title": title, "company": company, "location": location, "link": href})
            except Exception:
                continue

    return jobs


def scrape_via_dorking(previously_seen, new_links_to_save, remote_payloads):
    """DDGS Google-dork style searches for multiple platforms."""
    print("\n═══ PHASE 3: Search Engine Dorking ═══")

    dork_queries = [
        # Wellfound
        ('site:wellfound.com/jobs "Data Science" "Remote" ("Intern" OR "Working Student")', "Wellfound", "Remote (EU)"),
        ('site:wellfound.com/jobs "Machine Learning" "Remote" ("Intern" OR "Working Student")', "Wellfound", "Remote (EU)"),
        # Greenhouse boards
        ('site:boards.greenhouse.io ("working student" OR "intern") ("data science" OR "machine learning") Germany', "Greenhouse", "Germany/Remote"),
        ('site:boards.greenhouse.io ("working student" OR "intern") ("AI" OR "LLM") "Europe"', "Greenhouse", "Europe Remote"),
        # Lever
        ('site:jobs.lever.co ("working student" OR "intern") ("data" OR "ML") Germany', "Lever", "Germany/Remote"),
        # Ashby
        ('site:jobs.ashbyhq.com ("working student" OR "intern") ("data" OR "AI") Germany', "Ashby", "Germany/Remote"),
        # HN Who's Hiring (monthly thread)
        ('site:news.ycombinator.com "Who is Hiring" "working student" OR "intern" "data" "Germany" OR "Remote"', "HackerNews", "Remote"),
        # GermanTechJobs
        ('site:germantechjobs.de ("working student" OR "werkstudent") "data science"', "GermanTechJobs", "Germany"),
        ('site:germantechjobs.de ("working student" OR "werkstudent") "machine learning"', "GermanTechJobs", "Germany"),
        # EuroJobSites
        ('site:eurojobs.com ("working student" OR "intern") "data science" Germany', "EuroJobs", "Germany"),
    ]

    for query, platform, default_location in dork_queries:
        print(f"  → Dorking {platform}...")
        stats["sources_checked"] += 1
        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=10))
            for res in results:
                href = res.get("href", "")
                title = res.get("title", "")
                body = res.get("body", "")
                if not href or href in previously_seen or href in new_links_to_save:
                    continue

                stats["raw_jobs_seen"] += 1
                combined_text = f"{title} {body}"
                german = is_german_role(combined_text)
                company = _extract_company_from_dork(title, platform)
                score = calculate_priority(company, combined_text, is_german=german) + 5  # slight boost for dork hits

                if score > 10 and verify_company_legitimacy(company):
                    print(f"    ✅ [{platform}] {company} — {title[:60]}")
                    new_links_to_save.append(href)
                    previously_seen.add(href)
                    stats["new_jobs_found"] += 1
                    remote_payloads.append({
                        "score": score,
                        "company": company,
                        "title": title,
                        "link": href,
                        "source": platform,
                        "location": default_location,
                        "language": "DE" if german else "EN",
                    })
            time.sleep(2)  # Be polite to DDGS rate limits
        except Exception as e:
            print(f"    ✗ Dork failed for {platform}: {e}")
            stats["sources_failed"] += 1


def _extract_company_from_dork(title, platform):
    """Best-effort company name extraction from dork result titles."""
    separators = ["|", "–", "-", "at ", "@ "]
    for sep in separators:
        if sep in title:
            parts = title.split(sep)
            # Company name is usually the last or second-to-last segment
            candidate = parts[-1].strip() if len(parts) > 1 else parts[0].strip()
            if 2 < len(candidate) < 60:
                return candidate
    return platform  # Fallback to platform name


# ─────────────────────────────────────────────
# TELEGRAM DISPATCH
# ─────────────────────────────────────────────

def dispatch_jobs(payloads, header_emoji, header_text):
    if not payloads:
        return
    payloads.sort(key=lambda x: x["score"], reverse=True)
    current_chunk = f"{header_emoji} <b>{html.escape(header_text)}</b>\n\n"
    last_id = None

    for job in payloads:
        safe_title = html.escape(job["title"][:120])  # cap very long titles
        safe_company = html.escape(job["company"])
        safe_loc = html.escape(job["location"])
        lang_tag = " 🇩🇪" if job.get("language") == "DE" else ""
        source_tag = html.escape(job.get("source", ""))
        score_tag = job["score"]

        line = (
            f"<b>{safe_company}</b>{lang_tag} [★{score_tag}]\n"
            f"📍 {safe_loc} · {source_tag}\n"
            f"<a href='{job['link']}'>{safe_title}</a>\n\n"
        )
        if len(current_chunk) + len(line) > 3900:
            last_id = send_telegram_alert(current_chunk, reply_to=last_id)
            current_chunk = line
            time.sleep(1)
        else:
            current_chunk += line

    if current_chunk.strip():
        send_telegram_alert(current_chunk, reply_to=last_id)


def dispatch_health_report(dax_count, remote_count):
    elapsed = datetime.now() - stats["start_time"]
    minutes = int(elapsed.total_seconds() // 60)
    seconds = int(elapsed.total_seconds() % 60)

    msg = (
        f"📊 <b>Scraper Health Report</b>\n"
        f"🕒 {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
        f"✅ Sources checked: {stats['sources_checked']}\n"
        f"❌ Sources failed: {stats['sources_failed']}\n"
        f"👁️ Raw jobs seen: {stats['raw_jobs_seen']}\n"
        f"🆕 New jobs found: {stats['new_jobs_found']}\n"
        f"🏢 DAX/Direct: {dax_count}\n"
        f"🌍 Remote/Boards: {remote_count}\n"
        f"⏱️ Runtime: {minutes}m {seconds}s\n\n"
        f"<i>Score legend: +30 top company | +15 target role | +10/tech keyword (max 40) | -5 German title</i>"
    )
    send_telegram_alert(msg)


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def scrape_all():
    options = Options()
    options.page_load_strategy = "eager"

    if os.getenv("GITHUB_ACTIONS") == "true":
        print("DETECTED: GitHub Cloud Runner. Applying sandbox fixes...")
        options.add_argument("--headless")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")

    prefs = {
        "profile.managed_default_content_settings.images": 2,
        "profile.managed_default_content_settings.stylesheet": 2,
    }
    options.add_experimental_option("prefs", prefs)
    options.add_argument("--window-size=1920,1080")
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    driver.set_page_load_timeout(30)

    previously_seen = get_previously_seen_jobs()
    new_links_to_save = []
    dax_payloads = []
    remote_payloads = []

    print("═══════════════════════════════════")
    print("  MASTER JOB SCRAPER INITIATED")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("═══════════════════════════════════")

    # Phase 1: Direct portals
    scrape_direct_portals(driver, previously_seen, new_links_to_save, dax_payloads)

    # Phase 2: Job boards (Selenium)
    scrape_job_boards(driver, previously_seen, new_links_to_save, remote_payloads)

    driver.quit()

    # Phase 3: DDGS dorking (no browser needed)
    scrape_via_dorking(previously_seen, new_links_to_save, remote_payloads)

    # ── Telegram Dispatch ──
    dispatch_health_report(len(dax_payloads), len(remote_payloads))

    if dax_payloads:
        dispatch_jobs(dax_payloads, "🚨", "Elite Direct Portal Roles")
        print(f"Sent {len(dax_payloads)} DAX/Direct jobs.")
    
    if remote_payloads:
        dispatch_jobs(remote_payloads, "🌍", "Remote & Board Roles")
        print(f"Sent {len(remote_payloads)} Remote/Board jobs.")

    if not dax_payloads and not remote_payloads:
        print("No new jobs found this run.")

    save_new_jobs(new_links_to_save)
    print("\nDone. All new jobs saved.")


if __name__ == "__main__":
    scrape_all()