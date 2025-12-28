import os
import psycopg2
import torch
from dotenv import load_dotenv
from operator import itemgetter

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_core.messages import SystemMessage
import re

# Load environment
load_dotenv()
USER = os.getenv("DB_USER")
PASSWORD = os.getenv("DB_PASSWORD")
HOST = os.getenv("DB_HOST")
PORT = os.getenv("DB_PORT")
DBNAME = os.getenv("DB_NAME")
gemini_api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")

LLM_MODEL = "gemini-2.5-flash"
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
device = "cuda" if torch.cuda.is_available() else "cpu"

# Embeddings
embeddings = HuggingFaceEmbeddings(
    model_name=MODEL_NAME,
    model_kwargs={'device': device}
)

# Small cleaner for retrieved chunks
def preprocess_text(text: str) -> str:
    text = re.sub(r"\b\d{10}\b", "", text)  # remove phone numbers
    text = re.sub(r"\S+@\S+", "", text)    # remove emails
    text = " ".join(text.split())          # collapse whitespace
    return text.strip()

# Create RAG chain
def create_rag_chain(api_key):
    llm = ChatGoogleGenerativeAI(model=LLM_MODEL, google_api_key=api_key, temperature=0.4)

    template = """
    You are an intelligent course assistant.
    - Only answer using the provided context.
    - If unsure or context is insufficient, say:
      "I don't know. Please ask questions corresponding to the course plan."
    - Answer in great detail (minimum 4-5 lines).
    - Do not refer to the context like ( according to the given context, or anything like that, do not do that )

    Context:
    {context}

    Question:
    {question}

    Answer:
    """
    prompt = PromptTemplate.from_template(template)
    return (
        {"context": itemgetter("context"), "question": itemgetter("question")}
        | prompt
        | llm
        | StrOutputParser()
    )

rag_chain = create_rag_chain(gemini_api_key)

# Retrieve top-2 chunks
def extract_course_info_from_query(question_lc: str):
    """Attempt to extract course_code and course_name from the user's query using LLM, fallback to regex."""
    try:
        llm = ChatGoogleGenerativeAI(model=LLM_MODEL, google_api_key=gemini_api_key, temperature=0)
        prompt = (
            "Extract the course identifier and course name from the user query.\n"
            "Return ONLY a JSON object with keys: course_code, course_name. Use null for missing values.\n\n"
            f"User query: {question_lc}\n"
        )
        resp = llm.invoke([SystemMessage(content=prompt)])
        # try parse JSON from response
        import json
        try:
            parsed = json.loads(str(resp))
            return parsed.get("course_code"), parsed.get("course_name"), parsed.get("section")
        except Exception:
            pass
    except Exception:
        pass

    # Fallback regex (lowercase-friendly)
    code_match = re.search(r"\b([a-z]{2,5}\s*-?\s*\d{2,4}[a-z]?)\b", question_lc)
    course_code = code_match.group(1).replace(" ", "") if code_match else None

    # For course name, look for phrases after keywords
    name_match = re.search(r"(?:subject|course|title)[:\-\s]+([a-z0-9 &()\-/]+)", question_lc)
    course_name = name_match.group(1).strip() if name_match else None

    # Section fallback: look for 'section a' or 'part a' or standalone '(A)'
    sec_match = re.search(r"\b(?:section|part)[:\s-]*([ab])\b", question_lc)
    if not sec_match:
        sec_match = re.search(r"\(([abAB])\)", question_lc)
    section = sec_match.group(1).upper() if sec_match else None

    return course_code, course_name, section


def retrieve_top_chunks(question: str):
    # normalize query to lowercase first
    question_lc = (question or "").lower()

    conn = psycopg2.connect(host=HOST, database=DBNAME, user=USER, password=PASSWORD, port=PORT)
    cur = conn.cursor()

    q_vec = embeddings.embed_query(question)
    q_vec_str = "[" + ",".join(map(str, q_vec)) + "]"

    # Extract course info from user query (LLM + fallback)
    course_code, course_name, section = extract_course_info_from_query(question_lc)

    # Step 1 - Keyword search on metadata (course_code / course_name / title)
    # Use ILIKE with the extracted fields; fall back to searching the whole query
    try:
        if course_code or course_name:
            params = []
            clauses = []
            if course_code:
                clauses.append("course_code ILIKE %s")
                params.append(f"%{course_code}%")
            if course_name:
                clauses.append("course_name ILIKE %s")
                params.append(f"%{course_name}%")
            if section:
                clauses.append("section ILIKE %s")
                params.append(f"%{section}%")
            # also allow title search using the full query
            clauses.append("title ILIKE %s")
            params.append(f"%{question_lc}%")

            sql = f"SELECT id, circular_id, title FROM metadata WHERE {' OR '.join(clauses)} LIMIT 100;"
            cur.execute(sql, tuple(params))
            metadata_matches = cur.fetchall()
        else:
            cur.execute("""
                SELECT id, circular_id, title
                FROM metadata
                WHERE course_code ILIKE %s
                   OR course_name ILIKE %s
                   OR title ILIKE %s
                LIMIT 100;
            """, (f"%{question_lc}%", f"%{question_lc}%", f"%{question_lc}%"))
            metadata_matches = cur.fetchall()
    except Exception:
        metadata_matches = []

    metadata_ids = []
    if metadata_matches:
        for mid, circ_id, title in metadata_matches:
            metadata_ids.append(mid)

    # If no keyword matches, fall back to finding the nearest metadata by embedding
    if not metadata_ids:
        cur.execute("""
            SELECT metadata_id
            FROM content
            ORDER BY embedding <=> %s::vector
            LIMIT 1;
        """, (q_vec_str,))
        res = cur.fetchone()
        if not res:
            cur.close()
            conn.close()
            return []
        metadata_ids = [res[0]]

    # Step 2 - fetch top-6 chunks across the matched metadata_ids by embedding similarity
    cur.execute("""
        SELECT c.id, c.chunk_text, c.metadata_id, c.circular_id, m.title
        FROM content c
        JOIN metadata m ON c.metadata_id = m.id
        WHERE c.metadata_id = ANY(%s)
        ORDER BY c.embedding <=> %s::vector
        LIMIT 6;
    """, (metadata_ids, q_vec_str))

    rows = cur.fetchall()

    cleaned_docs = []
    circular_ids_used = set()
    for cid, chunk, mid, circular_id, title in rows:
        cleaned_chunk = preprocess_text(chunk)
        cleaned_docs.append(f"Title: {title}\n{cleaned_chunk}")
        if circular_id:
            circular_ids_used.add(circular_id)

    cur.close()
    conn.close()

    # Return both cleaned docs and set of circular ids used
    return cleaned_docs, circular_ids_used


# Ask Question
def ask_question_once(question: str) -> str:
    if not question.strip():
        return "Invalid question."

    result = retrieve_top_chunks(question)
    if not result:
        return "No relevant content found in DB."

    docs, circular_ids = result
    if not docs:
        return "No relevant content found in DB."

    context = "\n\n".join(docs)
    print(context)
    knows = True
    answer = rag_chain.invoke({"context": context, "question": question})
    if answer == "I don't know. Please ask questions corresponding to the course plan.":
        knows = False

    # For each used circular_id, fetch the PDF link from circulars table
    links = []
    if circular_ids:
        conn = psycopg2.connect(host=HOST, database=DBNAME, user=USER, password=PASSWORD, port=PORT)
        cur = conn.cursor()
        # fetch unique urls for the circular ids
        cur.execute("""
            SELECT DISTINCT id, url
            FROM circulars
            WHERE id = ANY(%s);
        """, (list(circular_ids),))
        for cid, url in cur.fetchall():
            if url:
                links.append(url)
        cur.close()
        conn.close()
        
    if not knows:
        links = []
    # Return a tuple: LLM answer and list of PDF links (one link per used circular)
    # The frontend should append the answer as a bot message, then append each link
    # as a separate bot message that contains ONLY the link text.
    return {"answer": answer, "links": links}

if __name__ == "__main__":
    question = input("Enter Question: ")
    print(ask_question_once(question))
