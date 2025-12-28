import asyncio
import aiohttp
import csv
import re
from bs4 import BeautifulSoup
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from sentence_transformers import SentenceTransformer
from supabase import create_client, Client
from Dreamer.dreamer import config
import time
import random
from tqdm import tqdm
import numpy as np

embedder = SentenceTransformer(config.EMBEDDING_MODEL)
dim = embedder.get_sentence_embedding_dimension()
if dim != config.EMBEDDING_DIM:
    raise RuntimeError(f"Embedding model produced dimension {dim}. Expected {config.EMBEDDING_DIM}.")

supabase: Client = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)

def render_html_as_text(html_content):
    if not html_content:
        return ""
    soup = BeautifulSoup(html_content, "html.parser")
    for br in soup.find_all(["br", "p", "div", "tr"]):
        br.append("\n")
    for li in soup.find_all("li"):
        li.insert_before("• ")
        li.append("\n")
    lines = [line.strip() for line in soup.get_text(separator="", strip=True).splitlines() if line.strip()]
    return "\n".join(lines)

def safe_upsert(table, chunk, retries=5):
    for attempt in range(retries):
        try:
            return supabase.table(table).upsert(chunk).execute()
        except Exception as e:
            msg = str(e)
            if "520" in msg or "502" in msg or "503" in msg or "504" in msg:
                wait = 2 + random.random() * 2
                print(f"Cloudflare error, retrying in {wait:.1f}s... (attempt {attempt+1})")
                time.sleep(wait)
            else:
                raise
    raise RuntimeError("Failed after retries")

def batched_supabase_insert(table, rows, batch_size=config.SUPABASE_BATCH_SIZE):
    total_batches = (len(rows) + batch_size - 1) // batch_size
    for i in tqdm(range(0, len(rows), batch_size), total=total_batches, desc="Uploading to Supabase"):
        chunk = rows[i:i+batch_size]
        safe_upsert(table, chunk)

def extract_minimal(job_data):
    placeholders = {item['type']: item['label'] for item in job_data.get('placeholders', [])}
    exp_text = job_data.get('experienceText', '')
    exp_match = re.findall(r'\d+', exp_text)
    min_exp = int(exp_match[0]) if exp_match else 0
    max_exp = int(exp_match[1]) if len(exp_match) > 1 else min_exp
    skills = [s.strip().lower() for s in job_data.get('tagsAndSkills', '').split(',') if s.strip()]
    created_ts = job_data.get('createdDate')
    if created_ts:
        try:
            posted_on = datetime.fromtimestamp(created_ts / 1000).strftime("%Y-%m-%d %H:%M:%S")
        except:
            posted_on = None
    else:
        posted_on = job_data.get('footerPlaceholderLabel', 'Unknown')
    return {
        "job_id": str(job_data.get("jobId")),
        "title": job_data.get("title") or "",
        "company": job_data.get("companyName") or "",
        "location": placeholders.get("location", ""),
        "min_exp": min_exp,
        "max_exp": max_exp,
        "salary": placeholders.get("salary", {}),
        "skills": ", ".join(skills),
        "description": render_html_as_text(job_data.get("jobDescription", "")),
        "posted_on": posted_on
    }

async def fetch_page(session, params, cookies, headers):
    async with session.get(
        "https://www.naukri.com/jobapi/v3/search",
        params=params,
        cookies=cookies,
        headers=headers
    ) as resp:
        if resp.status != 200:
            return []
        data = await resp.json()
        return data.get("jobDetails", [])

async def scrape_data_async(csv_file):
    options = Options()
    options.add_argument("--disable-blink-features=AutomationControlled")
    driver = webdriver.Chrome(options=options)
    driver.get(config.SCRAPER_BROWSER_URL)
    driver.implicitly_wait(5)
    cookie_dict = {c["name"]: c["value"] for c in driver.get_cookies()}
    user_agent = driver.execute_script("return navigator.userAgent;")
    driver.quit()

    headers = {
        'accept': 'application/json',
        'accept-language': 'en-US,en;q=0.9',
        'appid': config.SCRAPER_APPID,
        'clientid': config.SCRAPER_CLIENT_ID,
        'content-type': 'application/json',
        'gid': config.SCRAPER_REQUEST_HEADERS_GID,
        'priority': 'u=1, i',
        'referer': config.SCRAPER_BROWSER_URL,
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-origin',
        'systemid': 'Naukri',
        'user-agent': user_agent,
    }

    base_params = [
        ('urlType', 'search_by_location'),
        ('searchType', 'adv'),
        ('location', 'india'),
        ('sort', 'f'),
        ('experience', '0'),
        ('l', 'india'),
        ('seoKey', 'jobs-in-india-2'),
        ('src', 'directSearch'),
        ('latLong', ''),
        ('sid', '17619149253785296'),
    ]

    BATCH_SIZE = config.SCRAPER_BATCH_PAGES
    fieldnames = [
        'job_id', 'title', 'company', 'location', 'min_exp', 'max_exp',
        'salary', 'skills', 'description', 'posted_on'
    ]

    all_jobs = []
    seen = set()

    async with aiohttp.ClientSession() as session:
        with open(csv_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()

            page = 1
            total_jobs = 0

            while True:
                print(f"\n=== Fetching batch at page {page} ===")
                print("Jobs Covered:", total_jobs)

                batch_pages = list(range(page, page + BATCH_SIZE))

                tasks = []
                for p in batch_pages:
                    params = base_params + [("pageNo", str(p))]
                    tasks.append(fetch_page(session, params, cookie_dict, headers))

                results = await asyncio.gather(*tasks)

                if all(len(r) == 0 for r in results):
                    print("No more pages. Ending scrape.")
                    break

                for page_jobs in results:
                    for raw in page_jobs:
                        job = extract_minimal(raw)
                        job_id = job["job_id"]
                        if job_id in seen:
                            continue
                        seen.add(job_id)
                        writer.writerow(job)
                        all_jobs.append(job)
                        total_jobs += 1

                page += BATCH_SIZE

            print("Scraping complete. Total unique jobs:", total_jobs)

    if len(all_jobs) == 0:
        print("No jobs found. Skipping embeddings.")
        return

    def encode_to_float_lists(texts, prefix=config.EMBEDDING_INSTRUCTION, batch_size=128):
        embeddings = embedder.encode(
            [prefix + t for t in texts],
            batch_size=batch_size,
            show_progress_bar=True,
            convert_to_numpy=True,
            normalize_embeddings=False
        )
        embeddings = np.asarray(embeddings, dtype=np.float32)
        if embeddings.ndim != 2 or embeddings.shape[1] != dim:
            raise RuntimeError(f"Unexpected embedding shape: {embeddings.shape}")
        return embeddings.tolist()

    print("\nEmbedding titles...")
    titles = [job["title"] for job in all_jobs]
    emb_title = encode_to_float_lists(titles, prefix=config.EMBEDDING_INSTRUCTION, batch_size=64)

    print("\nEmbedding skills...")
    skills = [job["skills"] for job in all_jobs]
    emb_skills = encode_to_float_lists(skills, prefix=config.EMBEDDING_INSTRUCTION, batch_size=64)

    print("\nEmbedding descriptions...")
    descs = [job["description"] for job in all_jobs]
    emb_desc = encode_to_float_lists(descs, prefix=config.EMBEDDING_INSTRUCTION, batch_size=32)

    rows = []
    for job, t_emb, s_emb, d_emb in zip(all_jobs, emb_title, emb_skills, emb_desc):
        t_emb = [float(x) for x in t_emb]
        s_emb = [float(x) for x in s_emb]
        d_emb = [float(x) for x in d_emb]
        row = {
            "job_id": job["job_id"],
            "title": job["title"],
            "company": job["company"],
            "location": job["location"],
            "min_exp": job["min_exp"],
            "max_exp": job["max_exp"],
            "salary": job["salary"],
            "skills": job["skills"],
            "description": job["description"],
            "posted_on": job["posted_on"],
            "title_embedding": t_emb,
            "skills_embedding": s_emb,
            "desc_embedding": d_emb
        }
        rows.append(row)

    print("\nUploading to Supabase in safe batches...")
    batched_supabase_insert(config.SUPABASE_TABLE_JOBS, rows, batch_size=config.SUPABASE_BATCH_SIZE)
    print("\nAll unique jobs inserted successfully.")