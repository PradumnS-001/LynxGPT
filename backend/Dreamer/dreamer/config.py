import os
from dotenv import load_dotenv
load_dotenv()

# Files
FILES_DATABASE = "database.csv"
FILES_TEMP = "database_tmp.csv"
FILES_UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), "uploads")

# Supabase
SUPABASE_URL = os.getenv("SUPABASE_URL") or os.getenv("SUPABASE_URLD")
SUPABASE_KEY = os.getenv("SUPABASE_KEY") or os.getenv("SUPABASE_KEYD")
SUPABASE_TABLE_JOBS = "jobs"
TABLE_NAME = SUPABASE_TABLE_JOBS  # Alias for database.py

# Embedding
EMBEDDING_MODEL = "Fjoralb1/multilingual-e5-small-nli-matryoshka-128"
EMBEDDING_INSTRUCTION = "query: "
EMBEDDING_DIM = 128

# Scraper
SCRAPER_CSV_FILE = FILES_DATABASE
SCRAPER_BROWSER_URL = "https://www.naukri.com/jobs-in-india"
SCRAPER_BATCH_PAGES = 10
SCRAPER_FETCH_BATCH_SIZE = 50
SCRAPER_REQUEST_HEADERS_GID = "LOCATION,INDUSTRY,EDUCATION,FAREA_ROLE"
SCRAPER_CLIENT_ID = "d3skt0p"
SCRAPER_APPID = "109"

# Embedding upload batching
SUPABASE_BATCH_SIZE = 50

# Resume parsing
RESUME_FIELDS = ["Title", "Skills", "Description"]

# LLM and Ollama
OLLAMA_CMD = "ollama"

# Matching / similarity
MATCH_RPC_TITLE = "match_title"
MATCH_RPC_SKILLS = "match_skills"
MATCH_RPC_DESC = "match_desc"
MATCH_W_TITLE = 0.3
MATCH_W_SKILLS = 0.4
MATCH_W_DESC = 0.3
MATCH_TOP_K = 20
MATCH_TOP_N = 10

# Heuristics
MATCH_SKILL_WEIGHT = 0.8
MATCH_EXPERIENCE_WEIGHT = 0.2
EXPERIENCE_TOLERANCE_YEARS = 2
EXPERIENCE_TOLERANCE = EXPERIENCE_TOLERANCE_YEARS  # Alias for database.py

# Misc
GEMINI_API_KEY = os.getenv("GOOGLE_API_KEY") or os.getenv("LLM_API_KEY")
MODEL_GEMINI = os.getenv("LLM_MODEL") or "gemini-2.0-flash"