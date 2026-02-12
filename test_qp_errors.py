import os
import sys

# Ensure backend directory is in the path
backend_path = r"e:\lynx_gpt_main_2\final_lynx\LynxGPT\backend"
sys.path.append(backend_path)

# Correctly import from the module structure
from QuestionPapers.query_processor import get_link, extract_metadata_with_groq

test_queries = [
    "get me dsp paper", # Missing year and dept
    "cse 2023", # Missing subject
    "data structures", # Missing year and dept
    "show me cse papers from 2023 about automata", # Complete
    "get me the paper for 2025" # Invalid year?
]

print("--- Testing Question Paper Error Handling ---\n")

for query in test_queries:
    print(f"Query: '{query}'")
    try:
        # First check what metadata gets extracted
        # Since I can't easily import everything if dependencies are missing, let's wrap
        metadata = extract_metadata_with_groq(query)
        print(f"Extracted Metadata: {metadata}")
        
        # Then check the final response
        try:
            response = get_link(query)
            print(f"Final Response: {response}")
        except Exception as e:
            print(f"DB/Link Error: {e}")
            
    except Exception as e:
        print(f"LLM/Extraction Error: {e}")
    
    print("-" * 30 + "\n")
