import os
import json
import shutil
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pathlib import Path
import numpy as np
from Dreamer.dreamer import config
from Dreamer.dreamer.pipeline import run_resume_pipeline
from Dreamer.dreamer.utils import log_step

# Ensure uploads folder exists
os.makedirs(config.FILES_UPLOAD_FOLDER, exist_ok=True)

app = FastAPI()

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Config
UPLOAD_FOLDER = config.FILES_UPLOAD_FOLDER
MAX_FILE_SIZE = 16 * 1024 * 1024  # 16MB
ALLOWED_EXT = {".pdf"}


def allowed_file(filename: str) -> bool:
    return os.path.splitext(filename.lower())[1] in ALLOWED_EXT


def secure_filename(filename: str) -> str:
    """Simple filename sanitization."""
    return Path(filename).name.replace(" ", "_")


def normalize_scores(score_map: dict) -> dict:
    scores = np.array(list(score_map.values()), dtype=float)

    mean = scores.mean()
    std = scores.std()

    # avoid division by zero
    if std == 0:
        return {k: 0.5 for k in score_map}

    # Z-score to magnify tiny differences
    z = (scores - mean) / std

    # Sigmoid to convert to 0–1 nicely
    normalized = 1 / (1 + np.exp(-z))

    # Optional: stretch to 0.2–0.95 range for nicer UI
    normalized = 0.2 + normalized * 0.75

    # Return in same job_id order
    return {job_id: float(norm) for job_id, norm in zip(score_map.keys(), normalized)}


# -----------------------------
# ROUTES
# -----------------------------
@app.get("/", response_class=HTMLResponse)
async def index():
    """Serve the upload page."""
    template_path = Path(__file__).parent / "templates" / "upload.html"
    if template_path.exists():
        return template_path.read_text()
    return HTMLResponse(content="<h1>Resume Upload API</h1><p>POST /upload with a PDF file</p>")


@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    if not file or file.filename == "":
        raise HTTPException(status_code=400, detail="No file provided")
    
    if not allowed_file(file.filename):
        raise HTTPException(status_code=400, detail="Only PDF files allowed")
        
    # Check file size (streaming check or seek check)
    # Since we are using UploadFile, we can check the spool/size if available, or read chunks.
    # FastAPI UploadFile size might not be available until read.
    # But we can check after reading or seek to end.
    # Better: check content-length header if possible, or check after save.
    # Let's check file.size if available (FastAPI 0.100+) or just read.
    # Actually, simplistic check:
    file.file.seek(0, 2)
    size = file.file.tell()
    file.file.seek(0)
    
    if size > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail=f"File too large (max {MAX_FILE_SIZE/1024/1024}MB)")

    filename = secure_filename(file.filename)
    path = os.path.join(UPLOAD_FOLDER, filename)
    
    # Save uploaded file
    with open(path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    log_step("Web", f"Saved upload to {path}")

    try:
        log_step("Web", "Running resume → job match pipeline")
        result = run_resume_pipeline(path)

        candidate_info = result["candidate_info"]
        ranked_jobs = result["ranked_jobs"]

        if not ranked_jobs:
            return JSONResponse(content={
                "candidate_info": candidate_info,
                "jobs": [],
                "message": "No matching jobs found"
            })

        # -------------------------------
        # 🔥 APPLY NORMALIZATION HERE
        # -------------------------------
        # extract job_id→score mapping
        raw_score_map = {job["job_id"]: job["match_score"] for job in ranked_jobs}

        # normalize
        normalized_score_map = normalize_scores(raw_score_map)

        # apply back to ranked_jobs list
        for job in ranked_jobs:
            job_id = job["job_id"]
            job["match_score"] = normalized_score_map[job_id]

        # -------------------------------
        # Continue with formatting output
        # -------------------------------

        top_n_jobs = ranked_jobs[:config.MATCH_TOP_N]

        formatted = [
            {
                "id": job.get("job_id"),
                "job": job.get("title", "Untitled"),
                "score": float(job.get("match_score", 0)),
                "location": job.get("location"),
                "company": job.get("company"),
                "experience": f"{job.get('min_exp', 0)}–{job.get('max_exp', 0)} yrs",
                "employment_type": job.get("employment_type", "Not specified"),
            }
            for job in top_n_jobs
        ]

        return JSONResponse(content={
            "summary": candidate_info.get("Description") or "",
            "candidate_info": candidate_info,
            "top_jobs": formatted,
            "total_matches": len(formatted)
        })

    except Exception as e:
        log_step("Web", f"Error processing resume: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}")


# -----------------------------
# Server Run
# -----------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000)