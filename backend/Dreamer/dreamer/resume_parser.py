import fitz
import re
import json
from Dreamer.dreamer.utils import normalize_text, log_step
from Dreamer.dreamer import config
import google.generativeai as genai

genai.configure(api_key=config.GEMINI_API_KEY)
model = genai.GenerativeModel(config.MODEL_GEMINI)  # e.g., "gemini-1.5-flash" or "gemini-1.5-pro"


def extract_text_from_pdf(pdf_path):
    log_step("PDF Extraction", f"Reading file: {pdf_path}")
    try:
        doc = fitz.open(pdf_path)
        text = ""
        for page_num in range(len(doc)):
            page = doc[page_num]
            text += page.get_text()
        doc.close()
        log_step("PDF Extraction", f"Extracted {len(text)} characters")
        return text
    except Exception as e:
        log_step("PDF Extraction", f"Error: {str(e)}")
        raise


def clean_resume_text(raw_text):
    log_step("Text Cleaning", "Starting text cleanup")
    text = re.sub(r'[•●○■□▪▫◾◦⦿⦾]', '', raw_text)
    text = re.sub(r'Page \d+ of \d+', '', text, flags=re.IGNORECASE)
    text = re.sub(r'^\d+$', '', text, flags=re.MULTILINE)
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r' {2,}', ' ', text)
    lines = [line.strip() for line in text.split('\n')]
    text = '\n'.join(filter(None, lines))
    text = normalize_text(text)
    log_step("Text Cleaning", f"Cleaned text: {len(text)} characters")
    return text


# ------------------------------
# 2. Replace Ollama with Gemini
# ------------------------------
def run_gemini(model_name, prompt):
    try:
        response = model.generate_content(prompt)
        print(response)
        return response.text
    except Exception as e:
        log_step("LLM API", f"Gemini API error: {e}")
        raise


def create_extraction_prompt(resume_text):
    prompt = f"""
Extract the following information from this resume and return it as a JSON object:

1. Title: A list of job titles the candidate is best suited for based on their work history and skills.
2. Skills: A comma-separated list of technical and professional skills explicitly mentioned in the resume.
3. Description: A brief 2–4 line summary describing the candidate's overall professional background.

Resume text:
{resume_text}

Return ONLY a valid JSON object with these exact keys:
{{
  "Title": "",
  "Skills": "",
  "Description": ""
}}
"""
    return prompt


def call_llm_for_extraction(resume_text):
    log_step("LLM API", "Running Gemini for extraction")
    prompt = create_extraction_prompt(resume_text)

    try:
        output = run_gemini(config.MODEL_GEMINI, prompt)
        log_step("LLM API", "Received response from Gemini")
        return output
    except Exception as e:
        log_step("LLM API", f"Error calling Gemini: {str(e)}")
        raise


def parse_llm_response(llm_response):
    try:
        start = llm_response.find("{")
        end = llm_response.rfind("}") + 1
        if start != -1 and end > start:
            json_str = llm_response[start:end]
            return json.loads(json_str)
        else:
            return json.loads(llm_response)
    except json.JSONDecodeError as e:
        log_step("LLM Parsing", f"Error parsing JSON: {str(e)}\nResponse: {llm_response}")
        raise


def parse_resume(pdf_path):
    raw_text = extract_text_from_pdf(pdf_path)
    cleaned_text = clean_resume_text(raw_text)
    return cleaned_text


def extract_candidate_info(file_path):
    resume_text = parse_resume(file_path)
    log_step("Information Extraction", "Calling Gemini for extraction")

    retries = 5
    for i in range(retries):
        try:
            llm_response = call_llm_for_extraction(resume_text)
            data = parse_llm_response(llm_response)
            break
        except Exception as e:
            log_step("LLM Parsing", f"Error parsing JSON: {str(e)}... Retrying")

    required = config.RESUME_FIELDS
    for field in required:
        if field not in data or data[field] is None:
            data[field] = ""
    for field in required:
        if not isinstance(data[field], str):
            data[field] = str(data[field])

    log_step("Information Extraction", f"Extracted: {json.dumps(data, indent=2)}")
    return data