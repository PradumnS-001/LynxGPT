from sentence_transformers import SentenceTransformer
from supabase import create_client, Client
from Dreamer.dreamer import resume_parser
from Dreamer.dreamer import config

supabase: Client = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)
embedder = SentenceTransformer(config.EMBEDDING_MODEL)

def format_resume_for_embedding(resume_data):
    return (
        resume_data.get("Title", ""),
        resume_data.get("Skills", ""),
        resume_data.get("Description", "")
    )

def embed_resume_fields(title_text, skills_text, desc_text):
    emb_title = embedder.encode(title_text).tolist()
    emb_skills = embedder.encode(skills_text).tolist()
    emb_desc = embedder.encode(desc_text).tolist()
    return emb_title, emb_skills, emb_desc

def search_supabase(emb_title, emb_skills, emb_desc, k=config.MATCH_TOP_K):
    r1 = supabase.rpc(config.MATCH_RPC_TITLE, {
        "query_embedding": emb_title,
        "match_count": k
    }).execute().data
    r2 = supabase.rpc(config.MATCH_RPC_SKILLS, {
        "query_embedding": emb_skills,
        "match_count": k
    }).execute().data
    r3 = supabase.rpc(config.MATCH_RPC_DESC, {
        "query_embedding": emb_desc,
        "match_count": k
    }).execute().data
    return r1, r2, r3

def combine_scores(res_title, res_skills, res_desc,
                   w_title=config.MATCH_W_TITLE, w_skills=config.MATCH_W_SKILLS, w_desc=config.MATCH_W_DESC):
    score_map = {}
    def add_scores(results, weight):
        for row in results:
            job_id = row["job_id"]
            sim = float(row["similarity"])
            score_map[job_id] = score_map.get(job_id, 0) + sim * weight
    add_scores(res_title, w_title)
    add_scores(res_skills, w_skills)
    add_scores(res_desc, w_desc)
    return score_map

def fetch_jobs(job_ids):
    if not job_ids:
        return []
    response = supabase.table(config.SUPABASE_TABLE_JOBS).select("*").in_("job_id", job_ids).execute()
    return response.data

def rank_jobs(score_map, top_n=config.MATCH_TOP_N):
    sorted_ids = sorted(score_map, key=lambda x: score_map[x], reverse=True)
    top_ids = sorted_ids[:top_n]
    jobs = fetch_jobs(top_ids)
    for job in jobs:
        job["match_score"] = float(score_map[job["job_id"]])
    return jobs

def get_top_jobs(resume_data, k=config.MATCH_TOP_K, top_n=config.MATCH_TOP_N):
    title_text, skills_text, desc_text = format_resume_for_embedding(resume_data)
    emb_title, emb_skills, emb_desc = embed_resume_fields(
        title_text, skills_text, desc_text
    )
    res_title, res_skills, res_desc = search_supabase(
        emb_title, emb_skills, emb_desc, k=k
    )
    score_map = combine_scores(res_title, res_skills, res_desc)
    top_jobs = rank_jobs(score_map, top_n)
    top_jobs = [{j: i[j] for j in i if j not in ['title_embedding', 'skills_embedding', 'desc_embedding']} for i in top_jobs]
    return top_jobs


def rank_jobs_by_similarity(candidate_info, filtered_jobs, top_n=config.MATCH_TOP_N):
    """
    Rank pre-filtered jobs by similarity to candidate info.
    Used by pipeline.py when jobs are already filtered from database.
    """
    if not filtered_jobs:
        return []
    
    # Get candidate embeddings
    title_text, skills_text, desc_text = format_resume_for_embedding(candidate_info)
    cand_title_emb = embedder.encode(title_text)
    cand_skills_emb = embedder.encode(skills_text)
    cand_desc_emb = embedder.encode(desc_text)
    
    # Score each job
    scored_jobs = []
    for job in filtered_jobs:
        # Get job text fields
        job_title = job.get("title", "") or ""
        job_skills = job.get("key_skills", "") or ""
        job_desc = job.get("job_description", "") or ""
        
        # Compute embeddings for job
        job_title_emb = embedder.encode(job_title)
        job_skills_emb = embedder.encode(job_skills)
        job_desc_emb = embedder.encode(job_desc)
        
        # Cosine similarity (embeddings are normalized by SentenceTransformer)
        from numpy import dot
        from numpy.linalg import norm
        
        def cosine_sim(a, b):
            if norm(a) == 0 or norm(b) == 0:
                return 0.0
            return float(dot(a, b) / (norm(a) * norm(b)))
        
        score = (
            config.MATCH_W_TITLE * cosine_sim(cand_title_emb, job_title_emb) +
            config.MATCH_W_SKILLS * cosine_sim(cand_skills_emb, job_skills_emb) +
            config.MATCH_W_DESC * cosine_sim(cand_desc_emb, job_desc_emb)
        )
        
        job_copy = {k: v for k, v in job.items() if k not in ['title_embedding', 'skills_embedding', 'desc_embedding']}
        job_copy["match_score"] = score
        scored_jobs.append((job_copy, score))
    
    # Sort by score descending
    scored_jobs.sort(key=lambda x: x[1], reverse=True)
    
    # Return top N as list of (job, score) tuples
    return scored_jobs[:top_n]

if __name__ == "__main__":
    results = get_top_jobs(
        resume_parser.extract_candidate_info("resume-computer-engineering.pdf")
    )
    results = [(i["title"], i["match_score"]) for i in results]