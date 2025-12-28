import psycopg2
from psycopg2 import OperationalError
from dotenv import load_dotenv
import os
import fitz  # PyMuPDF
from PIL import Image
import io
from datetime import date
import torch
import pytesseract
import re
from langchain_huggingface import HuggingFaceEmbeddings
import time
import requests
import json
import nltk

nltk.download("punkt")
nltk.download("punkt_tab")
from nltk.tokenize import sent_tokenize

# --- Environment & Logging ---
load_dotenv()
# If needed on Windows:
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

device = "cuda" if torch.cuda.is_available() else "cpu"
model_name = "sentence-transformers/all-MiniLM-L6-v2"
TOP_N_CHARACTERS = 2000 # Increased for better context

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_API_URL = os.getenv("GROQ_API_URL")

USER = os.getenv("DB_USER")
PASSWORD = os.getenv("DB_PASSWORD")
HOST = os.getenv("DB_HOST")
PORT = os.getenv("DB_PORT")
DBNAME = os.getenv("DB_NAME")

embeddings = HuggingFaceEmbeddings(model_name=model_name, model_kwargs={"device": device})

# --- Retry helper ---
def retry_operation(func, *args, retries=5, delay=3, **kwargs):
    for attempt in range(retries):
        try: return func(*args, **kwargs)
        except Exception: time.sleep(delay)
    raise

# --- Improved Text Cleaner ---
def clean_text(text: str) -> str:
    # Remove PII
    text = re.sub(r"\b\d{10}\b", "", text)
    text = re.sub(r"\S+@\S+", "", text)
    
    # Selective keyword removal (removes words, not the whole line)
    remove_keywords = ["DEPARTMENT", "INSTITUTE", "TIRUCHIRAPPALLI", "Course Plan", "COURSE PLAN"]
    for word in remove_keywords:
        text = re.compile(re.escape(word), re.IGNORECASE).sub("", text)
    
    return " ".join(text.split()).strip()

# --- Improved PDF Extraction + Full Page OCR ---
def extract_pdf_text(filename, data):
    full_text = ""
    try:
        with fitz.open(stream=io.BytesIO(data), filetype="pdf") as doc:
            for page in doc:
                # 1. Standard text extraction
                page_text = page.get_text("text") or ""
                
                # 2. Trigger Full-Page OCR if page looks empty/scanned
                if len(page_text.strip()) < 100:
                    # Matrix(2,2) renders at 300 DPI for better OCR
                    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
                    img = Image.open(io.BytesIO(pix.tobytes()))
                    # PSM 3: Fully automatic page segmentation
                    page_text += "\n" + pytesseract.image_to_string(img, config="--oem 3 --psm 3")
                
                full_text += page_text
    except Exception as e:
        print(f"❌ Error in {filename}: {e}")
        
    return clean_text(full_text)

# --- Better Groq Prompt ---
def extract_course_info_with_groq(text: str, filename: str) -> dict:
    if not GROQ_API_KEY or not GROQ_API_URL:
        return {"course_code": None, "course_name": None}

    # Strict JSON formatting prompt
    prompt = f"""
    You are a data extraction bot. Below is text from an academic PDF titled "{filename}". 
    Extract the Course Code and Course Name into a JSON object.

    Guidelines:
    1. Course codes usually look like: EE201, CSPE56, CLPC21.
    2. Course names are titles like: "Basics of Electrical Circuits" or "Chemical Process Design".
    3. If the text is a time table, find the primary subject name.
    4. ONLY return a valid JSON object. Do not include markdown or explanations.

    Example Output: {{"course_code": "EE201", "course_name": "Digital Electronics"}}

    Text:
    {text[:TOP_N_CHARACTERS]}
    """

    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    data = {
        "model": os.getenv("GROQ_LLM_MODEL"),
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0,
        "response_format": {"type": "json_object"}
    }
    
    try:
        resp = requests.post(GROQ_API_URL, headers=headers, json=data, timeout=15)
        resp.raise_for_status()
        content = resp.json()['choices'][0]['message']['content']
        parsed = json.loads(content)
        # ensure section key exists (A or B)
        if 'section' not in parsed:
            parsed['section'] = None
        return parsed
    except Exception as e:
        print(f"⚠ Groq failed for {filename}: {e}")
        return {"course_code": None, "course_name": None}

# --- Rest of your original _check_connection_and_connect, chunk_text_smart, and _append_data logic remains here ---

def _check_connection_and_connect(dbname, user, password, host, port):
    conn = psycopg2.connect(dbname=dbname, user=user, password=password, host=host, port=port)
    conn.autocommit = False
    return conn

# --- Better Chunking (sentence-aware) ---
def chunk_text_smart(text, max_chars=900):
    sentences = sent_tokenize(text)
    chunks, current = [], ""
    for sent in sentences:
        if len(current) + len(sent) <= max_chars:
            current += " " + sent
        else:
            chunks.append(current.strip())
            current = sent
    if current:
        chunks.append(current.strip())
    return chunks


def derive_section_from_text_or_filename(text: str, filename: str):
    """Heuristic fallback to find Section A/B from text or filename."""
    if not text and not filename:
        return None

    t = (text or "").lower() + "\n" + (filename or "").lower()

    # Look for explicit patterns: 'section a', 'sec a', 'part a', '(a)'
    m = re.search(r"\b(?:section|sec|part)[:\s-]*([ab])\b", t, re.IGNORECASE)
    if m:
        return m.group(1).upper()

    m = re.search(r"\(([ab])\)", t)
    if m:
        return m.group(1).upper()

    # Look for trailing A/B tokens near course code patterns like 'CS301 A' or 'CS301-A'
    m = re.search(r"[a-z]{2,5}\s*-?\s*\d{2,4}[a-z]?\s*[-\s]\s*([ab])\b", t)
    if m:
        return m.group(1).upper()

    # filename patterns like '-A', '_A', ' A.pdf'
    m = re.search(r"[-_\s]([ab])(?:\.pdf)?$", (filename or ""), re.IGNORECASE)
    if m:
        return m.group(1).upper()

    return None

# --- Main logic (UPDATED) ---
def _append_data(embeddings, batch_size=5):
    """
    Process unhandled PDFs:
    - Extract & clean text
    - Embed full PDF text once
    - Chunk text smartly
    - Store metadata + chunks + SAME embedding per chunk
    """
    if embeddings is None:
        print("❌ Embedding model not loaded. Aborting.")
        return

    conn = _check_connection_and_connect(DBNAME, USER, PASSWORD, HOST, PORT)
    if not conn:
        print("❌ Database connection failed. Aborting.")
        return

    try:
        with conn.cursor() as cur:
            offset = 0

            while True:
                cur.execute("""
                    SELECT c.id, c.filename, c.data
                    FROM circulars c
                    LEFT JOIN metadata m ON LOWER(m.title) = LOWER(c.filename)
                    WHERE m.id IS NULL
                    ORDER BY c.uploaded_at DESC
                    LIMIT %s OFFSET %s;
                """, (batch_size, offset))
                rows = cur.fetchall()

                if not rows:
                    print("🎉 All PDFs processed!")
                    break

                print(f"\n📦 Fetching batch {(offset // batch_size) + 1} — {len(rows)} file(s)")
                ids, names, texts = [], [], []

                # Extract text
                for cid, fname, data in rows:
                    print(f"\n📄 Extracting text from: {fname}")
                    text = extract_pdf_text(fname, data)

                    if not text.strip():
                        print(f"⚠ No extractable text in {fname}, skipping.")
                        continue

                    ids.append(cid)
                    names.append(fname)
                    texts.append(text)

                if not ids:
                    print("⚠ All PDFs in this batch skipped due to empty text.")
                    offset += batch_size
                    continue

                # Embed entire PDF
                try:
                    vectors = embeddings.embed_documents(texts)
                except Exception as e:
                    print(f"❌ Embedding failed: {e}")
                    conn.rollback()
                    break

                current_date = date.today().strftime("%Y-%m-%d")

                # Insert metadata + chunks
                for cid, fname, full_text, vec in zip(ids, names, texts, vectors):
                    print(f"\n🔥 Processing document: {fname}")

                    if not isinstance(vec, list) or len(vec) == 0:
                        print(f"❌ Invalid vector embedding for {fname}, skipping.")
                        continue

                    vec_str = "[" + ",".join(map(str, vec)) + "]"
                    print(f"🧠 Embedding dimension: {len(vec)}")

                    # Extract course code/name from top of document and store metadata
                    top_text = (full_text or "")[:TOP_N_CHARACTERS]
                    course_info = extract_course_info_with_groq(top_text, fname)

                    # If LLM didn't provide section, try heuristic from text/filename/title
                    if not course_info.get('section'):
                        guessed = derive_section_from_text_or_filename(top_text, fname)
                        course_info['section'] = guessed

                    # Try inserting with `section` if the DB has that column, otherwise fall back
                    try:
                        cur.execute("""
                            INSERT INTO metadata (circular_id, title, upload_date, course_code, course_name, section)
                            VALUES (%s, %s, %s, %s, %s, %s)
                            RETURNING id;
                        """, (cid, fname, current_date, course_info.get('course_code'), course_info.get('course_name'), course_info.get('section')))
                    except Exception:
                        # fallback to older schema without section
                        cur.execute("""
                            INSERT INTO metadata (circular_id, title, upload_date, course_code, course_name)
                            VALUES (%s, %s, %s, %s, %s)
                            RETURNING id;
                        """, (cid, fname, current_date, course_info.get('course_code'), course_info.get('course_name')))
                    metadata_id = cur.fetchone()[0]
                    print(f"✔ Metadata stored — ID = {metadata_id}")

                    # Chunk text smartly
                    chunks = chunk_text_smart(full_text)
                    print(f"✂️ Created {len(chunks)} text chunks")

                    if not chunks:
                        print(f"⚠ No valid chunks found for {fname}")
                        continue

                    # Store chunks + embedding (attach circular_id too)
                    for idx, chunk in enumerate(chunks, 1):
                        cur.execute("""
                            INSERT INTO content (metadata_id, circular_id, chunk_text, embedding)
                            VALUES (%s, %s, %s, %s::vector);
                        """, (metadata_id, cid, chunk, vec_str))

                        if idx % 10 == 0 or idx == len(chunks):
                            print(f"→ Chunk {idx}/{len(chunks)} inserted")

                    print(f"🎯 Completed storing {fname}")

                conn.commit()
                offset += batch_size

    except Exception as e:
        print(f"🚨 Unexpected failure: {e}")
        conn.rollback()

    finally:
        conn.close()
        print("🔌 DB connection closed")


# --- API ---
def append_pdfs():
    _append_data(embeddings, batch_size=5)

# --- CLI ---
if __name__ == "__main__":
    append_pdfs()
