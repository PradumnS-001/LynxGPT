import pandas as pd
from supabase import create_client, Client
from Dreamer.dreamer.config import SUPABASE_URL, SUPABASE_KEY, TABLE_NAME, EXPERIENCE_TOLERANCE
from Dreamer.dreamer.utils import normalize_text, parse_experience_range, log_step


def get_supabase_client():
    """Initialize and return Supabase client"""
    return create_client(SUPABASE_URL, SUPABASE_KEY)


def import_jobs_from_csv(csv_path):
    """
    Import jobs from CSV file to Supabase table
    ASSUMPTION: CSV file has columns matching the table schema
    """
    log_step("CSV Import", f"Reading CSV from {csv_path}")
    
    # Read CSV
    df = pd.read_csv(csv_path)
    
    # Convert DataFrame to list of dictionaries
    jobs = df.to_dict('records')
    
    # Initialize Supabase client
    supabase = get_supabase_client()
    
    # Insert jobs in batches
    batch_size = 100
    total_inserted = 0
    
    for i in range(0, len(jobs), batch_size):
        batch = jobs[i:i+batch_size]
        try:
            # ASSUMPTION: Table name is "jobs" (from config.TABLE_NAME)
            supabase.table(TABLE_NAME).insert(batch).execute()
            total_inserted += len(batch)
            log_step("CSV Import", f"Inserted {total_inserted}/{len(jobs)} jobs")
        except Exception as e:
            log_step("CSV Import", f"Error inserting batch: {str(e)}")
    
    log_step("CSV Import", f"Successfully imported {total_inserted} jobs")
    return total_inserted


def filter_jobs_by_criteria(candidate_info):
    """
    Filter jobs from database based on candidate criteria:
    - department
    - role_category
    - experience (with tolerance)
    - education
    """
    log_step("SQL Filtering", "Filtering jobs by candidate criteria")
    
    supabase = get_supabase_client()
    
    # Start building query
    query = supabase.table(TABLE_NAME).select("*")
    
    # Filter by department (exact match)
    if candidate_info.get('department'):
        dept = candidate_info['department'].strip()
        query = query.ilike('department', f'%{dept}%')
    
    # Filter by role_category (exact match)
    if candidate_info.get('role_category'):
        role_cat = candidate_info['role_category'].strip()
        query = query.ilike('role_category', f'%{role_cat}%')
    
    # Filter by education (exact match or higher)
    if candidate_info.get('education'):
        edu = candidate_info['education'].strip()
        query = query.ilike('education', f'%{edu}%')
    
    # Execute query
    try:
        response = query.execute()
        jobs = response.data
        
        log_step("SQL Filtering", f"Found {len(jobs)} jobs after initial filtering")
        
        # Filter by experience range (post-query filtering for more flexibility)
        candidate_exp = candidate_info.get('experience', 0)
        filtered_jobs = []
        
        for job in jobs:
            job_exp_str = job.get('experience', '')
            min_exp, max_exp = parse_experience_range(job_exp_str)
            
            # Check if candidate experience is within job range (with tolerance)
            if (min_exp - EXPERIENCE_TOLERANCE <= candidate_exp <= max_exp + EXPERIENCE_TOLERANCE):
                filtered_jobs.append(job)
        
        log_step("SQL Filtering", f"Found {len(filtered_jobs)} jobs after experience filtering")
        return filtered_jobs
    
    except Exception as e:
        log_step("SQL Filtering", f"Error: {str(e)}")
        return []


def get_all_jobs():
    """Retrieve all jobs from database (for testing/debugging)"""
    supabase = get_supabase_client()
    try:
        response = supabase.table(TABLE_NAME).select("*").execute()
        return response.data
    except Exception as e:
        log_step("Database", f"Error fetching all jobs: {str(e)}")
        return []