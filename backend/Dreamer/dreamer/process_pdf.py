import os
import sys
import pdfplumber
from Dreamer.dreamer.info_extractor import extract_candidate_info
from Dreamer.dreamer.db_handler import DatabaseHandler
from Dreamer.dreamer.utils import log_step
import Dreamer.dreamer.config as config

os.makedirs(config.UPLOAD_FOLDER, exist_ok=True)

def pdf_to_text(path):
    text_parts = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            txt = page.extract_text() or ""
            text_parts.append(txt)
    return "\n".join(text_parts)

def process_file(path):
    log_step("Processor", f"Reading PDF: {path}")
    resume_text = pdf_to_text(path)
    if not resume_text.strip():
        log_step("Processor", "No text extracted from PDF")
        return None

    candidate_info = extract_candidate_info(resume_text)
    db = DatabaseHandler()
    inserted = db.store_candidate_info(candidate_info)
    log_step("Processor", "Processing complete")
    return {"candidate_info": candidate_info, "db_response": inserted}

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python process_pdf.py path\\to\\file.pdf")
        sys.exit(1)
    pdf_path = sys.argv[1]
    result = process_file(pdf_path)
    print(result)