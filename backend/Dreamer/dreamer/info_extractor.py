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

1. education: The highest level of education (e.g., "Bachelor's", "Master's", "PhD", "High School")
2. experience: Total years of experience as a single number (e.g., 5)
3. key_skills: A comma-separated list of technical and professional skills
4. department: The primary department/field (e.g., "Engineering", "Marketing", "Sales", "Finance", "HR")
5. role_category: The primary role category (e.g., "Software Development", "Data Science", "Marketing", "Sales")

Resume text:
{resume_text}

Return ONLY a valid JSON object with these exact keys:
{{
  "education": "",
  "experience": 0,
  "key_skills": "",
  "department": "",
  "role_category": ""
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
    
    except json.JSONDecodeError as e:
        log_step("LLM Parsing", f"Error parsing JSON: {str(e)}")
        raise


def extract_candidate_info(resume_text):
    """Main function to extract structured candidate information using LLM."""
    log_step("Information Extraction", "Calling LangChain LLM for extraction")
    
    # Call LLM
    llm_response = call_llm_for_extraction(resume_text)
    
    # Parse response
    candidate_info = parse_llm_response(llm_response)
    
    # Validate required fields
    required_fields = ['education', 'experience', 'key_skills', 'department', 'role_category']
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