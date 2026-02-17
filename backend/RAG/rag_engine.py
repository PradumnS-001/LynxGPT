import os
import re
import threading
import numpy as np
from typing import List, Dict, Tuple, Any, Optional
from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough
from langchain_core.output_parsers import StrOutputParser
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


# --- Custom Vector Store Class for Hybrid Search ---
class CustomSupabaseVectorStore(SupabaseVectorStore):
    """
    Custom vector store that supports hybrid search (BM25 + Semantic).
    Passes both the query embedding AND the raw query text to the RPC function.
    """
    def __init__(self, client, embedding, table_name, query_name):
        super().__init__(client=client, embedding=embedding, table_name=table_name, query_name=query_name)

    def similarity_search(
        self,
        query: str,
        k: int = 4,
        filter: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> List[Document]:
        vectors = self._embedding.embed_query(query)
        return [
            doc for doc, _ in self.similarity_search_with_score_by_vector(
                vectors, k, filter=filter, query_text=query
            )
        ]

    def similarity_search_with_score_by_vector(
        self,
        embedding: List[float],
        k: int = 4,
        filter: Optional[Dict[str, Any]] = None,
        query_text: str = "",
    ) -> List[Tuple[Document, float]]:
        docs_and_scores = []
        results = self.similarity_search_by_vector_returning_embeddings(
            embedding, k, filter=filter, query_text=query_text
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
        query_text: str = "",
    ) -> List[Tuple[Document, float, np.ndarray]]:
        # Parameters must match the Supabase function signature EXACTLY
        match_documents_params = dict(
            q_embed=query,
            q_text=query_text,
            match_c=k,
            match_thresh=0.0,
        )

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
                search.get("rrf_score", 0.0),  # Hybrid uses RRF score
                np.array([]),  # We don't need embeddings back for hybrid
            )
            for search in res.data
            if search.get("content")
        ]
        return match_result


# --- Initialization ---
_vector_store = None
_llm = None
_init_lock = threading.Lock()


def get_rag_resources():
    global _vector_store, _llm
    if _vector_store and _llm:
        return _vector_store, _llm

    with _init_lock:
        # Double-check after acquiring lock
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
                query_name="match_documents_hybrid",  # Function is in public schema
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
PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "You are an expert tutor. Answer the question using ONLY the provided context.\n\n"
     "CRITICAL RULES:\n"
     "0. **HONESTY:** If the context does not contain enough information to answer the question, "
     "say: 'I don't have enough information in my sources to answer this question. "
     "Please try rephrasing or asking about a specific topic from your syllabus.' "
     "Do NOT make up or hallucinate an answer.\n\n"
     "1. **MATH:** Do NOT use LaTeX or `$$` delimiters. Write formulas in plain text or using Unicode characters where possible.\n"
     "   - Example: Use 'E = mc^2' instead of '$$ E = mc^2 $$'.\n"
     "   - Use standard text representations (e.g., 'lambda', 'nu', 'sqrt()').\n\n"
     "2. **DIAGRAMS:** Do NOT generate Mermaid.js code or code blocks.\n"
     "   - Using words, bullet points, or numbered lists to describe the process or flow.\n"
     "   - If a diagram is requested, explain the structure textually.\n\n"
     "Context: {context}"),
    ("human", "{question}"),
])


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
        retriever = vector_store.as_retriever(search_kwargs={"k": 2})

        def format_docs(docs):
            return "\n\n".join(doc.page_content for doc in docs)

        # Build LCEL chain: retrieve docs -> format -> prompt -> LLM -> parse
        rag_chain = (
            {"context": retriever | format_docs, "question": RunnablePassthrough()}
            | PROMPT
            | llm
            | StrOutputParser()
        )

        response = rag_chain.invoke(query)

        # Clean latex just in case
        cleaned_response = clean_latex(response)

        return cleaned_response
    except Exception as e:
        return f"Error occurred during Subject QA: {e}"
