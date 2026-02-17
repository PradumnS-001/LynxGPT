"""Single entry point for running the resume-to-job-matches pipeline."""

from Dreamer.dreamer.resume_parser import parse_resume
from Dreamer.dreamer.info_extractor import extract_candidate_info
from Dreamer.dreamer.similarity import get_top_jobs
from Dreamer.dreamer.utils import log_step


def run_resume_pipeline(pdf_path):
    """
    Run the complete resume pipeline and return candidate info plus ranked jobs.

    Flow:
    1. Parse PDF → raw text
    2. LLM extracts Title, Skills, Description from resume
    3. Vector search via Supabase RPCs (match_title, match_skills, match_desc)
    4. Return ranked jobs with all fields

    Returns
    -------
    dict: {
        "candidate_info": dict,
        "ranked_jobs": list[dict],
    }
    """
    log_step("Pipeline", f"Starting pipeline for {pdf_path}")

    # Step 1: Parse resume PDF to text
    resume_text = parse_resume(pdf_path)
    if not resume_text.strip():
        raise ValueError("No text extracted from PDF")

    # Step 2: Extract structured info via LLM (Title, Skills, Description for embedding)
    candidate_info = extract_candidate_info(resume_text)

    # Step 3: Vector search — find closest jobs by embedding similarity
    ranked_jobs = get_top_jobs(candidate_info)

    if not ranked_jobs:
        log_step("Pipeline", "No jobs matched via vector search")
    else:
        log_step("Pipeline", f"Found {len(ranked_jobs)} matched jobs")

    return {
        "candidate_info": candidate_info,
        "ranked_jobs": ranked_jobs,
    }

