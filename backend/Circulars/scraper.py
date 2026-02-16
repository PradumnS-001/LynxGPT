import os
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import urllib3
from dotenv import load_dotenv
import psycopg2
from datetime import datetime, timedelta
import time

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = "https://cp.nitt.edu/filesview.php"
ROOT_URL = "https://cp.nitt.edu/"
HEADERS = {"User-Agent": "Mozilla/5.0"}

num = None
upper_limit = None

visited_pages = set()
pdf_urls = set()
limit_reached = False

def safe_get(url, stream=False):
    """Retry wrapper to prevent infinite hanging."""
    for attempt in range(5):
        try:
            resp = requests.get(
                url,
                headers=HEADERS,
                stream=stream,
                verify=False,
                timeout=30  # KEY FIX
            )
            return resp
        except Exception as e:
            print(f"Request failed ({attempt+1}/5): {e}")
            time.sleep(4)
    raise RuntimeError(f"Failed after 5 attempts: {url}")

def scrape_folder(fid=None):
    global num, limit_reached

    if limit_reached:
        return

    url = BASE_URL if fid is None else f"{BASE_URL}?page=filesview&fid={fid}"
    print(f"Scanning folder: {url}")

    if url in visited_pages:
        return
    visited_pages.add(url)

    resp = safe_get(url)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    time.sleep(0.5)  # prevent throttling

    for tag in soup.find_all(attrs={"data-source": True}):
        src = tag.get("data-source")
        if not src:
            continue
        if src.lower().endswith(".pdf"):
            if num is not None and num >= upper_limit:
                print(f"Reached testing limit {upper_limit}")
                limit_reached = True
                return
            pdf_url = urljoin(ROOT_URL, f"assets/uploads/{src}")
            pdf_urls.add(pdf_url)
            if num is not None:
                num += 1

    for div in soup.select(".folder-item[data-id]"):
        folder_id = div.get("data-id")
        if folder_id:
            scrape_folder(folder_id)

def get_db_conn():
    
    load_dotenv()
    database_url = os.getenv("DATABASE_URL") or os.getenv("SUPABASE_DATABASE_URL")
    if database_url:
        return psycopg2.connect(database_url, sslmode="require")

    user = os.getenv("CIRCULAR_DB_USER")
    dbname = os.getenv("CIRCULAR_DB_NAME")
    password = os.getenv("CIRCULAR_DB_PASSWORD")
    host = os.getenv("CIRCULAR_DB_HOST")
    port = os.getenv("CIRCULAR_DB_PORT")

    dsn = f"host={host} port={port} dbname={dbname} user={user} password={password} sslmode=require"
    return psycopg2.connect(dsn)

def ensure_table(conn):
    pass

def delete_old_pdfs(conn, months=5):
    cutoff_date = datetime.now() - timedelta(days=months * 30)
    with conn.cursor() as cur:
        cur.execute("DELETE FROM circulars WHERE uploaded_at < %s", (cutoff_date,))
        conn.commit()

def delete_duplicate_by_filename(conn, filename):
    with conn.cursor() as cur:
        cur.execute("DELETE FROM circulars WHERE filename=%s", (filename,))
        conn.commit()

def upload_pdf_to_db(url, conn):
    filename = url.split("/")[-1]

    with conn.cursor() as cur:
        cur.execute("SELECT id FROM circulars WHERE url=%s", (url,))
        if cur.fetchone():
            print(f"Exists → {filename}")
            return

    delete_duplicate_by_filename(conn, filename)

    print(f"Downloading: {filename}")
    resp = safe_get(url, stream=True)  # timeout + retry
    data = resp.content
    time.sleep(0.5)

    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO circulars (filename, url, data) VALUES (%s,%s,%s) RETURNING id",
            (filename, url, psycopg2.Binary(data))
        )
        conn.commit()

def scrape_update():
    conn = None
    try:
        conn = get_db_conn()
        ensure_table(conn)
        delete_old_pdfs(conn, months=5)
    except Exception as e:
        print(f"No DB: {e}")

    scrape_folder()

    for u in sorted(pdf_urls):
        if conn:
            try:
                upload_pdf_to_db(u, conn)
            except Exception as e:
                print(f"Upload failed: {e}")

    if conn:
        conn.close()

def main():
    from append_data import append_pdfs
    scrape_update()
    append_pdfs()

if __name__ == "__main__":
    main()
