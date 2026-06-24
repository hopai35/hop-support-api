"""
Hop Support - Core RAG Engine

This module provides the core RAG (Retrieval-Augmented Generation) logic,
including document ingestion, vector storage, retrieval, and LLM-based
response generation.

The system uses ChromaDB for vector storage and supports multiple LLM providers
for response generation.
"""

import os
import glob
import logging
from typing import List, Dict, Optional
from pathlib import Path

import chromadb
from chromadb.config import Settings

logger = logging.getLogger(__name__)


class RAGEngine:
    """
    Core RAG Engine for Hop Support's AI customer support system.

    Handles document ingestion, semantic retrieval, and LLM-based response
    generation using a configurable provider.
    """

    def __init__(
        self,
        persist_dir: str = "data/chroma",
        collection_name: str = "hop_support_kb",
        llm_provider: str = "mock",
        llm_model: str = "gpt-4o-mini",
        openai_api_key: Optional[str] = None,
    ):
        """
        Initialize the RAG Engine.

        Args:
            persist_dir: Directory for ChromaDB persistence.
            collection_name: Name of the ChromaDB collection.
            llm_provider: LLM provider ('openai' or 'mock').
            llm_model: Model name for the LLM.
            openai_api_key: OpenAI API key (required for 'openai' provider).
        """
        self.persist_dir = persist_dir
        self.collection_name = collection_name
        self.llm_provider = llm_provider
        self.llm_model = llm_model
        self.openai_api_key = openai_api_key or os.getenv("OPENAI_API_KEY")

        # Initialize ChromaDB
        os.makedirs(persist_dir, exist_ok=True)
        self._connect_chroma()

        logger.info(
            f"RAGEngine initialized (provider={llm_provider}, "
            f"model={llm_model}, collection={collection_name})"
        )

    def _connect_chroma(self):
        """Connect to ChromaDB and get or create the collection."""
        self.chroma_client = chromadb.PersistentClient(
            path=self.persist_dir,
            settings=Settings(anonymized_telemetry=False),
        )
        # Get existing collection or create it
        try:
            self.collection = self.chroma_client.get_collection(
                name=self.collection_name,
            )
            logger.info(
                f"Connected to existing collection '{self.collection_name}' "
                f"({self.collection.count()} documents)"
            )
        except (ValueError, chromadb.errors.NotFoundError):
            self.collection = self.chroma_client.create_collection(
                name=self.collection_name,
            )
            logger.info(
                f"Created new collection '{self.collection_name}'"
            )

    def reset_collection(self):
        """Delete and recreate the collection (for re-ingestion)."""
        try:
            self.chroma_client.delete_collection(self.collection_name)
        except (ValueError, chromadb.errors.NotFoundError):
            pass
        self.collection = self.chroma_client.create_collection(
            name=self.collection_name,
        )
        logger.info(f"Collection '{self.collection_name}' has been reset")

    def ingest_documents(self, kb_dir: str) -> int:
        """
        Ingest all markdown documents from a directory into the vector store.

        Args:
            kb_dir: Path to the knowledge base directory containing .md files.

        Returns:
            Number of document chunks ingested.
        """
        kb_path = Path(kb_dir)
        if not kb_path.exists():
            raise FileNotFoundError(f"Knowledge base directory not found: {kb_dir}")

        md_files = glob.glob(str(kb_path / "**/*.md"), recursive=True)
        md_files.extend(glob.glob(str(kb_path / "**/*.txt"), recursive=True))

        if not md_files:
            logger.warning(f"No markdown or text files found in {kb_dir}")
            return 0

        all_chunks = []
        all_ids = []
        all_metadata = []
        chunk_id = 0

        for file_path in sorted(md_files):
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            # Extract title from first heading or use filename
            title = Path(file_path).stem
            for line in content.split("\n"):
                if line.startswith("# "):
                    title = line.lstrip("# ").strip()
                    break

            # Split document into chunks by sections (## headings) or paragraphs
            chunks = self._chunk_document(content, title)

            for i, chunk_text in enumerate(chunks):
                if chunk_text.strip():
                    all_chunks.append(chunk_text)
                    all_ids.append(f"{chunk_id}")
                    all_metadata.append({
                        "source": str(file_path),
                        "title": title,
                        "chunk_index": i,
                    })
                    chunk_id += 1

        if all_chunks:
            self.collection.add(
                documents=all_chunks,
                ids=all_ids,
                metadatas=all_metadata,
            )
            logger.info(f"Ingested {len(all_chunks)} chunks from {len(md_files)} files")
        else:
            logger.warning("No content chunks extracted from documents")

        return len(all_chunks)

    def _chunk_document(self, content: str, title: str) -> List[str]:
        """
        Split a document into chunks for embedding.

        Uses section headers (##) as natural boundaries, with fallback
        to paragraph splitting.

        Args:
            content: The full document text.
            title: Document title (prepended to each chunk).

        Returns:
            List of text chunks.
        """
        lines = content.split("\n")
        chunks = []
        current_chunk = [f"# {title}"]

        for line in lines:
            # Start new chunk at ## headings (but keep # headings as intro)
            if line.startswith("## ") and len(current_chunk) > 3:
                chunks.append("\n".join(current_chunk).strip())
                current_chunk = [f"# {title}", line]
            else:
                current_chunk.append(line)

        # Add the last chunk
        remaining = "\n".join(current_chunk).strip()
        if remaining:
            chunks.append(remaining)

        # Further split any chunk that's too long (>1000 chars) by paragraphs
        final_chunks = []
        for chunk in chunks:
            if len(chunk) > 1000:
                paragraphs = chunk.split("\n\n")
                temp = []
                for para in paragraphs:
                    if temp and len("\n\n".join(temp + [para])) > 1000:
                        final_chunks.append("\n\n".join(temp))
                        temp = [para]
                    else:
                        temp.append(para)
                if temp:
                    final_chunks.append("\n\n".join(temp))
            else:
                final_chunks.append(chunk)

        return final_chunks

    def retrieve(self, query: str, top_k: int = 3) -> List[Dict]:
        """
        Retrieve relevant context chunks for a query.

        Args:
            query: The user's question.
            top_k: Number of chunks to retrieve.

        Returns:
            List of dicts with 'content', 'source', and 'title' keys.
        """
        collection_size = self.collection.count()
        if collection_size == 0:
            logger.warning("Collection is empty, no results to retrieve")
            return []

        n_results = min(top_k, collection_size)

        results = self.collection.query(
            query_texts=[query],
            n_results=n_results,
        )

        retrieved = []
        if results["documents"] and results["documents"][0]:
            for i, doc in enumerate(results["documents"][0]):
                metadata = results["metadatas"][0][i] if results["metadatas"] else {}
                retrieved.append({
                    "content": doc,
                    "source": metadata.get("source", "unknown"),
                    "title": metadata.get("title", "Untitled"),
                })

        logger.info(f"Retrieved {len(retrieved)} chunks for query: {query[:50]}...")
        return retrieved

    def generate_response(self, query: str, context: List[Dict]) -> str:
        """
        Generate a response based on retrieved context using the configured LLM.

        Args:
            query: The user's question.
            context: List of retrieved context chunks.

        Returns:
            Generated response text.
        """
        if self.llm_provider == "openai":
            return self._generate_openai(query, context)
        else:
            return self._generate_mock(query, context)

    def _generate_mock(self, query: str, context: List[Dict]) -> str:
        """
        Generate a mock response without an LLM (for testing/demo).

        This uses the top retrieved chunk directly as the response.
        """
        if not context:
            return (
                "I couldn't find any relevant information in the knowledge base "
                "to answer your question. Please try rephrasing or contact a "
                "human agent for assistance."
            )

        sources = [c["title"] for c in context]
        top_chunk = context[0]["content"]

        response = (
            f"Based on the information in our knowledge base"
            f"{' (from: ' + ', '.join(set(sources)) + ')' if sources else ''}, "
            f"I can provide the following information:\n\n{top_chunk}"
        )

        return response

    def _generate_openai(self, query: str, context: List[Dict]) -> str:
        """
        Generate a response using OpenAI's API.
        """
        if not self.openai_api_key:
            logger.warning("No OpenAI API key available, falling back to mock")
            return self._generate_mock(query, context)

        try:
            from openai import OpenAI

            client = OpenAI(api_key=self.openai_api_key)

            # Build context string
            context_str = "\n\n".join([
                f"[Source: {c['title']}]\n{c['content']}" for c in context
            ])

            system_prompt = (
                "You are a helpful customer support AI assistant for Hop Support. "
                "Use the following knowledge base context to answer the customer's "
                "question accurately. If the context doesn't contain the answer, "
                "say so honestly. Be concise, friendly, and professional.\n\n"
                f"Knowledge base context:\n{context_str}"
            )

            response = client.chat.completions.create(
                model=self.llm_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": query},
                ],
                max_tokens=500,
                temperature=0.3,
            )

            return response.choices[0].message.content

        except Exception as e:
            logger.error(f"OpenAI API error: {e}")
            return (
                "I encountered an error while generating a response. "
                "Please try again later or contact support."
            )

    def query(self, query: str, top_k: int = 3) -> Dict:
        """
        End-to-end query: retrieve context and generate a response.

        Args:
            query: The user's question.
            top_k: Number of context chunks to retrieve.

        Returns:
            Dict with 'answer', 'sources', and 'query' keys.
        """
        context = self.retrieve(query, top_k=top_k)
        answer = self.generate_response(query, context)

        return {
            "answer": answer,
            "sources": [
                {"title": c["title"], "source": c["source"]} for c in context
            ],
            "query": query,
        }