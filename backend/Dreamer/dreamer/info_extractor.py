"""Info extractor module - extracts structured candidate information using LangChain."""

import json
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage

from Dreamer.dreamer.utils import log_step
import Dreamer.dreamer.config as config

# Initialize LangChain Gemini model (lazy loading)
_llm = None

def _get_llm():
    """Get or create the LangChain LLM instance."""
    global _llm
    if _llm is None:
        if not config.GEMINI_API_KEY:
            raise ValueError("GOOGLE_API_KEY/LLM_API_KEY is not set. Please update your .env file.")
        
        _llm = ChatGoogleGenerativeAI(
            model=config.MODEL_GEMINI,
            google_api_key=config.GEMINI_API_KEY,
            temperature=0.2,
            max_output_tokens=2048,
        )
    return _llm


def create_extraction_prompt(resume_text):
    """Create LLM prompt for structured information extraction."""
    return f"""Extract the following information from this resume and return it as a JSON object:

1. Title: The candidate's desired job title or current role (e.g., "Data Scientist", "Software Developer", "PHP Developer")
2. Skills: A comma-separated list of technical and professional skills
3. Description: A brief professional summary of the candidate (2-3 sentences)
4. experience: Total years of experience as a single number (e.g., 5)
5. education: The highest level of education (e.g., "Bachelor's", "Master's", "PhD", "High School")
6. is_resume: Boolean true/false. Set to false if this document is NOT a CV/resume (e.g. it is a research paper, thesis, receipt, invoice, or random text).

Resume text:
{resume_text}

Return ONLY a valid JSON object with these exact keys:
{{
  "Title": "",
  "Skills": "",
  "Description": "",
  "experience": 0,
  "education": "",
  "is_resume": true
}}"""


def call_llm_for_extraction(resume_text):
    """Call LangChain LLM to extract structured information from resume."""
    log_step("LLM API", "Initializing LangChain Gemini client")

    llm = _get_llm()
    prompt = create_extraction_prompt(resume_text)

    try:
        messages = [
            SystemMessage(content="You are a helpful AI assistant that extracts structured information from resumes. Always return responses in valid JSON format."),
            HumanMessage(content=prompt)
        ]
        response = llm.invoke(messages)
        log_step("LLM API", "Successfully received response from LangChain Gemini")
        return response.content

    except Exception as e:
        log_step("LLM API", f"Error calling LangChain Gemini: {str(e)}")
        raise


def parse_llm_response(llm_response):
    """Parse LLM response and extract JSON."""
    try:
        # Try to find JSON in the response
        json_start = llm_response.find('{')
        json_end = llm_response.rfind('}') + 1
        
        if json_start != -1 and json_end > json_start:
            json_str = llm_response[json_start:json_end]
            data = json.loads(json_str)
            return data
        else:
            # If no JSON found, try parsing the whole response
            data = json.loads(llm_response)
            return data
    
    except (json.JSONDecodeError, ValueError) as e:
        log_step("LLM Parsing", f"Error parsing JSON: {str(e)}\nRaw Response: {llm_response}")
        # If the LLM didn't return JSON (e.g. it returned a refusal "I cannot read this"), 
        # assume it's not a valid resume.
        return {"is_resume": False}


def extract_candidate_info(resume_text):
    """Main function to extract structured candidate information using LLM."""
    log_step("Information Extraction", "Calling LangChain LLM for extraction")
    
    # Retry loop for LLM robustness
    max_retries = 5
    candidate_info = {}
    
    for attempt in range(max_retries):
        try:
            # Call LLM
            llm_response = call_llm_for_extraction(resume_text)
            
            # Parse response
            candidate_info = parse_llm_response(llm_response)
            
            # Check if it's actually a resume
            if candidate_info.get("is_resume") is False:
                raise ValueError("The uploaded document does not appear to be a valid resume/CV.")
                
            break # Success!
        except ValueError as ve:
             # If it's the "not a resume" error, don't retry—just fail immediately
             raise ve
        except Exception as e:
            log_step("Information Extraction", f"Attempt {attempt+1}/{max_retries} failed: {str(e)}")
            if attempt == max_retries - 1:
                log_step("Information Extraction", "All retries failed. Failing pipeline.")
                raise RuntimeError(f"Failed to extract info after {max_retries} attempts: {e}")
    
    # Validate required fields
    required_fields = ['Title', 'Skills', 'Description', 'experience', 'education']
    for field in required_fields:
        if field not in candidate_info:
            candidate_info[field] = ""
    
    # Ensure experience is numeric
    try:
        candidate_info['experience'] = int(candidate_info['experience'])
    except (ValueError, TypeError):
        candidate_info['experience'] = 0
    
    log_step("Information Extraction", f"Extracted: {json.dumps(candidate_info, indent=2)}")
    return candidate_info