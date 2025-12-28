from supabase import create_client
from Dreamer.dreamer.config import SUPABASE_URL, SUPABASE_KEY
from Dreamer.dreamer.utils import log_step

class DatabaseHandler:
    def __init__(self):
        if not SUPABASE_URL or not SUPABASE_KEY:
            raise RuntimeError("Supabase credentials missing in .env")
        self.client = create_client(SUPABASE_URL, SUPABASE_KEY)

    def store_candidate_info(self, candidate_info):
        """Insert into 'candidates' table; returns inserted record."""
        try:
            res = self.client.table("candidates").insert(candidate_info).execute()
            log_step("Database", "Stored candidate info")
            return getattr(res, "data", res)
        except Exception as e:
            log_step("Database", f"Error storing data: {e}")
            raise