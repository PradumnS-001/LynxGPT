import os
import json
from flask import Flask, request, render_template, jsonify
from flask_cors import CORS
from werkzeug.utils import secure_filename
import numpy as np
from Dreamer.dreamer import config
from Dreamer.dreamer import resume_parser
from Dreamer.dreamer import similarity
from Dreamer.dreamer.utils import format_job_result, log_step

# Ensure uploads folder exists
os.makedirs(config.FILES_UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})
app.config["UPLOAD_FOLDER"] = config.FILES_UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16MB

ALLOWED_EXT = {".pdf"}

def allowed_file(filename):
    return os.path.splitext(filename.lower())[1] in ALLOWED_EXT


# -----------------------------
# Main Pipeline for Resume → Jobs
# -----------------------------
def run_resume_pipeline(pdf_path):
    log_step("Pipeline", f"Running resume extraction for: {pdf_path}")

    candidate_info = resume_parser.extract_candidate_info(pdf_path)
    log_step("Pipeline", f"Candidate Info Extracted")

    # ADD DEBUG: print the extracted candidate info
    print("\n[DEBUG] candidate_info returned from Resume_Parser:")
    print(json.dumps(candidate_info, indent=2))

    ranked_jobs = similarity.get_top_jobs(candidate_info)
    log_step("Pipeline", f"Similarity search complete")

    # ADD DEBUG: print the ranked_jobs list from Similarity
    print("\n[DEBUG] ranked_jobs returned from Similarity.get_top_jobs:")
    print(json.dumps(ranked_jobs, indent=2))

    return {
        "candidate_info": candidate_info,
        "ranked_jobs": ranked_jobs
    }

def normalize_scores(score_map):
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
@app.route("/", methods=["GET"])
def index():
    return render_template("upload.html")


@app.route("/upload", methods=["POST"])
def upload():
    file = request.files.get("file")

    if not file or file.filename == "":
        return jsonify({"error": "No file provided"}), 400
    if not allowed_file(file.filename):
        return jsonify({"error": "Only PDF files allowed"}), 400

    filename = secure_filename(file.filename)
    path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    file.save(path)

    log_step("Web", f"Saved upload to {path}")

    try:
        log_step("Web", "Running resume → job match pipeline")
        result = run_resume_pipeline(path)

        candidate_info = result["candidate_info"]
        ranked_jobs = result["ranked_jobs"]

        if not ranked_jobs:
            response_data = {
                "candidate_info": candidate_info,
                "jobs": [],
                "message": "No matching jobs found"
            }
            return jsonify(response_data)

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

        response_data = {
            "summary": candidate_info.get("Description") or "",
            "candidate_info": candidate_info,
            "top_jobs": formatted,
            "total_matches": len(formatted)
        }
        return jsonify(response_data)

    except Exception as e:
        log_step("Web", f"Error processing resume: {str(e)}")
        return jsonify({"error": f"Processing failed: {str(e)}"}), 500


# -----------------------------
# Server Run
# -----------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)