import json
import sys
from Dreamer.dreamer.database import import_jobs_from_csv
from Dreamer.dreamer.pipeline import run_resume_pipeline
from Dreamer.dreamer.utils import format_job_result
from Dreamer.dreamer.config import TOP_N_RESULTS


def process_resume_and_find_jobs(resume_path):
    """
    Main pipeline:
    1. Extract text from resume PDF
    2. Extract structured information using LLM
    3. Filter jobs from database
    4. Rank jobs by similarity
    5. Return top N matches
    """
    
    print("="*60)
    print("RESUME-BASED JOB FINDER PIPELINE")
    print("="*60)
    
    print("\n[1/3] Running resume pipeline...")
    pipeline_result = run_resume_pipeline(resume_path)
    candidate_info = pipeline_result["candidate_info"]
    ranked_jobs = pipeline_result["ranked_jobs"]

    print("\n[2/3] Candidate Profile:")
    print(json.dumps(candidate_info, indent=2))

    if not ranked_jobs:
        print("\n⚠ No jobs found matching the criteria.")
        return []

    print(f"\n[3/3] Retrieving top {TOP_N_RESULTS} matches...")
    top_jobs = ranked_jobs[:TOP_N_RESULTS]
    
    # Format results
    results = [format_job_result(job, score) for job, score in top_jobs]
    
    print("\n" + "="*60)
    print(f"TOP {len(results)} JOB MATCHES")
    print("="*60)
    
    for i, result in enumerate(results, 1):
        print(f"\n#{i} (Score: {result['score']})")
        print(f"Title: {result['name']}")
        print(f"Location: {result['location']}")
        print(f"Department: {result['department']}")
        print(f"Experience: {result['experience']}")
        print(f"Skills: {result['key_skills']}")
        print(f"Employment: {result['employment_type']}")
    
    return results


def import_jobs_to_database(csv_path):
    """Import jobs from CSV to Supabase database"""
    print("\n" + "="*60)
    print("IMPORTING JOBS TO DATABASE")
    print("="*60)
    
    # ASSUMPTION: CSV file path is provided by user
    total = import_jobs_from_csv(csv_path)
    print(f"\n✓ Successfully imported {total} jobs to database")


def main():
    """Entry point with command-line interface"""
    
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python main.py <resume.pdf>           # Find jobs for resume")
        print("  python main.py --import <jobs.csv>    # Import jobs to database")
        sys.exit(1)
    
    # Import mode
    if sys.argv[1] == "--import":
        if len(sys.argv) < 3:
            print("Error: Please provide CSV file path")
            print("Usage: python main.py --import <jobs.csv>")
            sys.exit(1)
        
        csv_path = sys.argv[2]  # ASSUMPTION: CSV file path from command line
        import_jobs_to_database(csv_path)
    
    # Job matching mode
    else:
        resume_path = sys.argv[1]  # ASSUMPTION: Resume PDF path from command line
        results = process_resume_and_find_jobs(resume_path)
        
        # Optionally save results to JSON
        output_file = "job_matches.json"
        with open(output_file, 'w') as f:
            json.dump(results, f, indent=2)
        
        print(f"\n✓ Results saved to {output_file}")


if __name__ == "__main__":
    main()