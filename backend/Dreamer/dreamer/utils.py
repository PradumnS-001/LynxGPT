import re
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def normalize_text(text):
    if not text:
        return ""
    text = re.sub(r'\s+', ' ', text)
    return text.strip().lower()

def normalize_skills(skills_str):
    if not skills_str:
        return set()
    skills = [s.strip().lower() for s in str(skills_str).split(',')]
    return set(filter(None, skills))

def parse_experience_range(exp_str):
    if not exp_str:
        return (0, 100)
    exp_str = str(exp_str).strip().lower()
    range_match = re.search(r'(\d+)\s*-\s*(\d+)', exp_str)
    if range_match:
        return (int(range_match.group(1)), int(range_match.group(2)))
    plus_match = re.search(r'(\d+)\s*\+', exp_str)
    if plus_match:
        return (int(plus_match.group(1)), 100)
    num_match = re.search(r'(\d+)', exp_str)
    if num_match:
        num = int(num_match.group(1))
        return (num, num)
    return (0, 100)

def calculate_weighted_score(skill_score, exp_score, skill_weight=0.7):
    exp_weight = 1.0 - skill_weight
    return (skill_score * skill_weight) + (exp_score * exp_weight)

def log_step(step_name, details=""):
    logger.info(f"[{step_name}] {details}")

def format_job_result(job, score):
    return {
        'score': round(score, 3),
        'name': job.get('name'),
        'location': job.get('location'),
        'role': job.get('role'),
        'department': job.get('department'),
        'experience': job.get('experience'),
        'education': job.get('education'),
        'key_skills': job.get('key_skills'),
        'employment_type': job.get('employment_type')
    }