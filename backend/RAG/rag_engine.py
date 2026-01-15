import os
import re
import numpy as np
from typing import List, Dict, Tuple, Any, Optional
from langchain_core.documents import Document
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_groq import ChatGroq
from langchain_classic.chains import RetrievalQA
from langchain_classic.prompts import PromptTemplate
from langchain_community.vectorstores import SupabaseVectorStore
from supabase.client import create_client

# --- Monkey Patch for Supabase/Postgrest >= 2.23.0 ---
try:
    from postgrest._sync.request_builder import SyncRPCFilterRequestBuilder
    if not hasattr(SyncRPCFilterRequestBuilder, "params"):
        def get_params(self):
            return self.request.params

        def set_params(self, value):
            self.request.params = value

        SyncRPCFilterRequestBuilder.params = property(get_params, set_params)
except ImportError:
    pass

# --- Custom Vector Store Class ---
class CustomSupabaseVectorStore(SupabaseVectorStore):
    def similarity_search(
        self,
        query: str,
        k: int = 4,
        filter: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> List[Document]:
        vectors = self._embedding.embed_query(query)
        return [
            doc for doc, _ in self.similarity_search_with_score_by_vector(vectors, k, filter=filter)
        ]

    def similarity_search_with_score_by_vector(
        self,
        embedding: List[float],
        k: int = 4,
        filter: Optional[Dict[str, Any]] = None,
    ) -> List[Tuple[Document, float]]:
        docs_and_scores = []
        results = self.similarity_search_by_vector_returning_embeddings(
            embedding, k, filter=filter
        )
        for doc, score, _ in results:
            docs_and_scores.append((doc, score))
        return docs_and_scores

    def similarity_search_by_vector_returning_embeddings(
        self,
        query: List[float],
        k: int,
        filter: Optional[Dict[str, Any]] = None,
        postgrest_filter: Optional[str] = None,
    ) -> List[Tuple[Document, float, np.ndarray]]:
        match_documents_params = dict(
            query_embedding=query,
            match_count=k, 
            match_threshold=0.0
        )
        if filter:
            match_documents_params["filter"] = filter

        query_builder = self._client.rpc(self.query_name, match_documents_params)

        if postgrest_filter:
            query_builder.params = query_builder.params.set(
                "and", f"({postgrest_filter})"
            )
            
        res = query_builder.execute()

        match_result = [
            (
                Document(
                    metadata=search.get("metadata", {}),
                    page_content=search.get("content", ""),
                ),
                search.get("similarity", 0.0),
                np.fromstring(
                    search.get("embedding", "").strip("[]"), np.float32, sep=","
                ),
            )
            for search in res.data
            if search.get("content")
        ]
        return match_result

# --- Initialization ---
_vector_store = None
_llm = None

def get_rag_resources():
    global _vector_store, _llm
    if _vector_store and _llm:
        return _vector_store, _llm

    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_KEY")
    groq_api_key = os.getenv("GROQ_API_KEY")

    if not supabase_url or not supabase_key or not groq_api_key:
        print("RAG: Missing env variables (SUPABASE_URL, SUPABASE_SERVICE_KEY, GROQ_API_KEY)")
        return None, None

    try:
        embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
        supabase_client = create_client(supabase_url, supabase_key)
        
        _vector_store = CustomSupabaseVectorStore(
            client=supabase_client,
            embedding=embeddings,
            table_name="metadata.documents",
            query_name="metadata.match_documents",
        )

        _llm = ChatGroq(
            temperature=0.2,
            model_name="openai/gpt-oss-20b", 
            groq_api_key=groq_api_key
        )
        return _vector_store, _llm
    except Exception as e:
        print(f"RAG: Initialization failed: {e}")
        return None, None

# --- Prompt ---
custom_prompt_template = """
You are an expert tutor. Answer the question using the context.

CRITICAL RULES FOR FORMATTING:
1. **MATH:** Do NOT use LaTeX or `$$` delimiters. Write formulas in plain text or using Unicode characters where possible.
   - Example: Use "E = mc^2" instead of "$$ E = mc^2 $$".
   - Use standard text representations (e.g., "lambda", "nu", "sqrt()").

2. **DIAGRAMS:** Do NOT generate Mermaid.js code or code blocks.
   - Using words, bullet points, or numbered lists to describe the process or flow.
   - If a diagram is requested, explain the structure textually.

Context: {context}
Question: {question}
Answer:
"""
PROMPT = PromptTemplate(template=custom_prompt_template, input_variables=["context", "question"])

def clean_latex(text):
    # Remove any accidental LaTeX delimiters that might still appear
    text = text.replace("$$", "").replace("$", "")
    return text


def ask_subject_qa(query: str) -> str:
    """
    Main entry point for Subject QA.
    """
    vector_store, llm = get_rag_resources()
    if not vector_store or not llm:
        return "Sorry, the Subject QA module is not configured correctly (missing keys or connection failed)."

    try:
        qa_chain = RetrievalQA.from_chain_type(
            llm=llm,
            chain_type="stuff",
            retriever=vector_store.as_retriever(search_kwargs={"k": 2}),
            chain_type_kwargs={"prompt": PROMPT}
        )
        
        result = qa_chain.invoke({"query": query})
        response = result["result"]
        
        # Clean latex just in case
        cleaned_response = clean_latex(response)
        
        return cleaned_response
    except Exception as e:
        return f"Error occurred during Subject QA: {e}"
