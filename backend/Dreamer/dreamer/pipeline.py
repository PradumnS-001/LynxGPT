"""Single entry point for running the resume-to-job-matches pipeline."""

from Dreamer.dreamer.resume_parser import parse_resume
from Dreamer.dreamer.info_extractor import extract_candidate_info
from Dreamer.dreamer.database import filter_jobs_by_criteria
from Dreamer.dreamer.similarity import rank_jobs_by_similarity
from Dreamer.dreamer.utils import log_step


def run_resume_pipeline(pdf_path):
    """
    Run the complete resume pipeline and return candidate info plus ranked jobs.

    Returns
    -------
    dict: {
        "candidate_info": dict,
        "ranked_jobs": list[(job_dict, score)],
    }
    """
    log_step("Pipeline", f"Starting pipeline for {pdf_path}")

    resume_text = parse_resume(pdf_path)
    if not resume_text.strip():
        raise ValueError("No text extracted from PDF")

    candidate_info = extract_candidate_info(resume_text)
    filtered_jobs = filter_jobs_by_criteria(candidate_info)

    if not filtered_jobs:
        log_step("Pipeline", "No jobs matched filter criteria")
        ranked_jobs = []
    else:
        ranked_jobs = rank_jobs_by_similarity(candidate_info, filtered_jobs)
        log_step("Pipeline", f"Ranked {len(ranked_jobs)} jobs")

    return {
        "candidate_info": candidate_info,
        "ranked_jobs": ranked_jobs,
    }
