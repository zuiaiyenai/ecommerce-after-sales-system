"""Rebuild all knowledge chunk embeddings using the current embedding provider.

Usage:
    python -m evaluation.rebuild_embeddings [--dry-run] [--batch-size 10]
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from after_sales_agent.retrieval.pgvector_retriever import PgVectorConfig, PgVectorKnowledgeRetriever


def rebuild_embeddings(dry_run: bool = False, batch_size: int = 10):
    """Rebuild all knowledge chunk embeddings."""
    config = PgVectorConfig.from_env()
    
    print("=" * 60)
    print("Knowledge Embedding Rebuild")
    print("=" * 60)
    print(f"Provider: {config.embedding_provider}")
    print(f"Model: {config.embedding_model}")
    print(f"Dimensions: {config.dimensions}")
    print(f"Dry run: {dry_run}")
    print(f"Batch size: {batch_size}")
    print()
    
    # Connect to PostgreSQL
    try:
        import psycopg
    except ImportError:
        print("Error: psycopg not installed")
        return
    
    dsn = config.dsn
    if not dsn:
        print("Error: PGVECTOR_DSN not configured")
        return
    
    # Query all chunks
    print("Fetching all knowledge chunks...")
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT kc.id, kc.chunk_text, kc.document_id
                FROM knowledge_chunk kc
                JOIN knowledge_document kd ON kc.document_id = kd.id
                WHERE kd.status = 1
                ORDER BY kc.id
            """)
            chunks = cur.fetchall()
    
    print(f"Found {len(chunks)} chunks to rebuild")
    print()
    
    if dry_run:
        print("Dry run mode - no changes will be made")
        for chunk_id, chunk_text, doc_id in chunks[:5]:
            print(f"  Chunk {chunk_id} (doc {doc_id}): {chunk_text[:50]}...")
        if len(chunks) > 5:
            print(f"  ... and {len(chunks) - 5} more")
        return
    
    # Initialize embedding service
    retriever = PgVectorKnowledgeRetriever(config)
    embedding_service = retriever._embedding_service
    
    # Rebuild embeddings in batches
    total_start = time.time()
    success_count = 0
    error_count = 0
    
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i:i + batch_size]
        batch_texts = [chunk_text for _, chunk_text, _ in batch]
        batch_ids = [chunk_id for chunk_id, _, _ in batch]
        
        print(f"Processing batch {i // batch_size + 1}/{(len(chunks) + batch_size - 1) // batch_size}: chunks {batch_ids[0]}-{batch_ids[-1]}...")
        
        try:
            # Generate embeddings
            embeddings = embedding_service.embed_many(batch_texts)
            
            # Update database
            with psycopg.connect(dsn) as conn:
                with conn.cursor() as cur:
                    for chunk_id, embedding in zip(batch_ids, embeddings):
                        # Convert list to pgvector format
                        vector_str = "[" + ",".join(str(v) for v in embedding) + "]"
                        cur.execute(
                            "UPDATE knowledge_chunk SET embedding = %s::vector WHERE id = %s",
                            (vector_str, chunk_id)
                        )
                conn.commit()
            
            success_count += len(batch)
            print(f"  Updated {len(batch)} chunks")
            
        except Exception as e:
            error_count += len(batch)
            print(f"  Error: {e}")
        
        # Small delay to avoid rate limiting
        if i + batch_size < len(chunks):
            time.sleep(0.1)
    
    total_elapsed = time.time() - total_start
    
    print()
    print("=" * 60)
    print("Rebuild Complete")
    print("=" * 60)
    print(f"Total chunks: {len(chunks)}")
    print(f"Success: {success_count}")
    print(f"Errors: {error_count}")
    print(f"Total time: {total_elapsed:.1f}s")
    print(f"Avg time per chunk: {total_elapsed / len(chunks) * 1000:.1f}ms")


def main():
    parser = argparse.ArgumentParser(description="Rebuild knowledge chunk embeddings")
    parser.add_argument("--dry-run", action="store_true", help="Dry run mode (no changes)")
    parser.add_argument("--batch-size", type=int, default=10, help="Batch size for embedding")
    
    args = parser.parse_args()
    rebuild_embeddings(dry_run=args.dry_run, batch_size=args.batch_size)


if __name__ == "__main__":
    main()
