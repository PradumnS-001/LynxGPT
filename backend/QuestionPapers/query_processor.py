import requests
import json
import os
from dotenv import load_dotenv
from supabase import create_client, Client # Import Supabase

# --- Configuration ---
# --- Removed OLLAMA, using Groq instead ---
load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_API_URL = os.getenv("GROQ_API_URL")
GROQ_LLM_MODEL = os.getenv("GROQ_LLM_MODEL") # Keeping your requested model

# --- Supabase Configuration ---
supabase_URL = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_SERVICE_KEY")

if not GROQ_API_KEY:
    print("[ERROR] GROQ_API_KEY not found in .env file.")
if not supabase_URL or not supabase_key:
    print("[ERROR] SUPABASE_URL or SUPABASE_SERVICE_KEY not found in .env file.")


def extract_metadata_with_groq(query_text: str) -> dict:
    """Uses Groq to extract metadata (dept, subject, year, exam_type) from a user query."""
    print(f"INFO: Sending query to Groq ({GROQ_LLM_MODEL}) for metadata extraction: '{query_text}'")
    
    prompt = f"""
You are an expert at analyzing user queries about question papers and extracting key metadata into a JSON object. Your goal is to identify the department, subject, year, and exam_type.

Follow these rules exactly:
1.  **Output Format:** Respond ONLY with a single, valid JSON object. Do not include any explanations, reasoning, or markdown.
2.  **Fields:** You must extract "department", "subject", "year", and "exam_type".
3.  **Full Subject Extraction:** When a subject is mentioned, extract the **fullest possible name** of the subject, not just one keyword. (e.g., "design and analysis of algorithms", not "algorithms").

4.  **Subject Normalization:** You **must** convert the extracted subject name to **all lowercase**.

5.  **Department Standardization (CRITICAL):** You must normalize all department names (full names, common typos, abbreviations) to their standard abbreviation.
    * `computer science and engineering`, `computer science & engineering`, `computr science`, `cs` -> `cse`
    * `electronics and communication engineering` -> `ece`
    * `electrical and electronics engineering` -> `eee`
    * `instrumentation and control engineering` -> `ice`
    * `mechanical engineering` -> `mech`
    * `chemical engineering` -> `chem`
    * `production engineering` -> `prod`
    * `metallurgical and material science engineering` -> `mme`
    * `civil engineering` -> `civil`
    * If the department is not in this list, output it as-is.

6.  **Disambiguation (NEW RULE):** A phrase identified as the department (e.g., "computer science and engineering") **CANNOT** also be extracted as the subject. The subject must be a separate topic.

7.  **Robust Subject Typo Correction:** You **must** correct common misspellings in *subject* names.
    * `algoritms` -> `algorithms`
    * `desing and analyis` -> `design and analysis`

8.  **Year:** Extract the four-digit year.

9.  **exam_type (Logic):** Look for keywords to determine the exam type.
    * If the query contains "End Semester", "End Sem", "Sem End", "Degree Examination", "Final", output: `endsem`.
    * If the query contains "Mid Semester", "Mid Sem", output: `midsem`.
    * If none of the above are found (or if it says "Cycle Test", "CT", "Assessment","cycle test","ct","cycletest") output: `ct`.

10. **Completeness:** If a value is genuinely not present or ambiguous, use `null`. (This rule is for you, the model, even though the examples below are all complete).

[EXAMPLE 1 - UPDATED]
Query: "find papers for cse department from 2023 on data structures"
JSON Output: {{"department": "cse", "subject": "data structures", "year": "2023", "exam_type": "ct"}}

[EXAMPLE 2 - UPDATED]
Query: "show me the 2021 endsem algoritms papers from computr science"
JSON Output: {{"department": "cse", "subject": "algorithms", "year": "2021", "exam_type": "endsem"}}

[EXAMPLE 3 - UPDATED]
Query: "any mid sem question paper for mech 2022 on thermodynamics?"
JSON Output: {{"department": "mech", "subject": "thermodynamics", "year": "2022", "exam_type": "midsem"}}

[EXAMPLE 4 - UPDATED]
Query: "get me computer science and engineering desing and analyis of algorithms of 2023 paper"
JSON Output: {{"department": "cse", "subject": "design and analysis of algorithms", "year": "2023", "exam_type": "ct"}}

[EXAMPLE 5 - NEW]
Query: "get me Computer science and engineering 2023 automata and formal languages paper"
JSON Output: {{"department": "cse", "subject": "automata and formal languages", "year": "2023", "exam_type": "ct"}}

Now, analyze the following query:

Query: "{query_text}"
JSON Output:
"""
    headers = { "Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json" }
    data = {
        "model": GROQ_LLM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "response_format": {"type": "json_object"}
    }

    try:
        response = requests.post(GROQ_API_URL, headers=headers, json=data, timeout=30)
        response.raise_for_status()
        response_data = response.json()
        message_content = response_data['choices'][0]['message']['content']
        metadata = json.loads(message_content)
        
        # Ensure all expected keys are present, defaulting to None
        for key in ['department', 'subject', 'year', 'exam_type']:
            if key not in metadata:
                metadata[key] = None
                
        print(f"INFO: Metadata extracted by Groq: {metadata}")
        return metadata
    except Exception as e:
        print(f"[ERROR] Groq API request failed: {e}")
        return {'department': None, 'subject': None, 'year': None, 'exam_type': None, 'error': str(e)}

def search_database(client: Client, metadata: dict) -> (list, str): # type: ignore
    """Builds and runs a query using the Supabase client."""
    
    # Added exam_type to the select statement
    query = client.schema('metadata').table('metadata').select('department, subject, year, file_url, exam_type')
    query_details = "SELECT department, subject, year, file_url, exam_type FROM metadata.metadata WHERE "
    filters_applied = []

    try:
        if metadata.get("department"):
            query = query.eq('department', metadata['department'])
            filters_applied.append(f"department = '{metadata['department']}'")

        if metadata.get("subject"):
            # Split subject into words for a more robust "AND" search
            words = str(metadata['subject']).split()
            for word in words:
                query = query.ilike('subject', f'%{word}%')
            filters_applied.append(f"subject ILIKE '%{metadata['subject']}%'") # Simplified for logging

        if metadata.get("year"):
            try:
                year_val = int(metadata['year'])
                if 1900 < year_val < 2100:
                    query = query.eq('year', year_val)
                    filters_applied.append(f"year = {year_val}")
                else:
                    print(f"[WARN] Invalid year '{metadata['year']}' extracted, ignoring.")
            except (ValueError, TypeError):
                print(f"[WARN] Non-integer year '{metadata['year']}' extracted, ignoring.")

        # --- NEW: Exam Type Filter ---
        if metadata.get("exam_type"):
            query = query.eq('exam_type', metadata['exam_type'])
            filters_applied.append(f"exam_type = '{metadata['exam_type']}'")

        # Add ordering
        query = query.order('year', desc=True).order('department').order('subject')
        
        # Build the log string
        if filters_applied:
            query_details += " AND ".join(filters_applied)
        else:
            query_details += "1=1" # No filters
        query_details += " ORDER BY year DESC, department, subject;"

        print(f"INFO: Executing Supabase query...")
        response = query.execute()
        results = response.data
        print(f"INFO: Query executed successfully, found {len(results)} results.")
        return results, query_details

    except Exception as e:
        print(f"[ERROR] Supabase query failed: {e}")
        error_message = f"Database query failed: {e}"
        return [{"error": error_message}], query_details + " [ERROR]"


def process_user_query(user_query: str) -> dict:
    """Orchestrates the query processing pipeline."""
    
    # 1. Extract metadata from query using Groq
    metadata = extract_metadata_with_groq(user_query)
    if 'error' in metadata:
        return {"error": f"LLM failed: {metadata['error']}", "results": []}

    # 2. Create a fresh Supabase client (avoids connection errors)
    client = None
    try:
        if not supabase_URL or not supabase_key:
            raise Exception("SUPABASE_URL or SUPABASE_SERVICE_KEY not set.")
        client: Client = create_client(supabase_URL, supabase_key)
        print("INFO: Supabase client initialized for query.")
    except Exception as e:
        print(f"[ERROR] Failed to initialize Supabase client: {e}")
        return {"error": f"Database connection failed: {e}", "results": []}

    # 3. Search the database
    db_results, query_log = search_database(client, metadata)
    
    # Check if the database itself returned an error
    if db_results and isinstance(db_results[0], dict) and 'error' in db_results[0]:
         db_error = db_results[0]['error']
         return {"metadata": metadata, "sql": query_log, "error": db_error, "results": []}

    return {
        "metadata": metadata,
        "sql": query_log, # For the Streamlit expander
        "results": db_results
    }
    
def get_link(test_query: str) -> str:
    output = process_user_query(test_query)
    return output['results'][0]['file_url']

# --- Example Usage (for testing this script directly) ---
if __name__ == '__main__':
    test_query = "show me cse papers from 2023 about automata and formal languages"
    # test_query = "mech paper 2022"
    # test_query = "computer science and engineering desing and analyis of algorithms of 2023"
    
    output = process_user_query(test_query)
    print("\n--- Final Output ---")
    print(json.dumps(output, indent=2, default=str))