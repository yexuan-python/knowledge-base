# Qdrant Vector Store Design

## Goal

Add Qdrant as an optional lightweight vector-store backend while keeping Milvus as the default backend and preserving the existing application-level vector-store method contract.

## Architecture

The application keeps calling a store object through the methods already implemented by `MilvusVectorStore`. A new `QdrantVectorStore` implements the same methods for chunk vectors and fact vectors. `build_infrastructure()` selects the backend from `KB_VECTOR_STORE`, so deployment can switch between Milvus and Qdrant through environment configuration.

## Configuration

- `KB_VECTOR_STORE` accepts `milvus` or `qdrant`; default is `milvus`.
- Qdrant uses `KB_QDRANT_URL`, `KB_QDRANT_API_KEY`, `KB_QDRANT_COLLECTION_NAME`, `KB_QDRANT_FACTS_COLLECTION_NAME`, `KB_QDRANT_ON_DISK_VECTORS`, and `KB_QDRANT_TIMEOUT_SECONDS`.
- Existing Milvus settings stay available for rollback.

## Data Mapping

- Chunk rows are stored in the Qdrant chunks collection with the existing chunk `id` as the point id, the embedding as the vector, and all searchable metadata in payload.
- Fact rows are stored in the Qdrant facts collection with `fact_id` as the point id, the embedding as the vector, and fact metadata in payload.
- Search results are normalized to the same fields currently returned by `MilvusVectorStore.search()` and `search_facts()`.

## Scope

This change adds runtime backend selection and Qdrant support. It does not remove Milvus, migrate existing data automatically, or alter the ingestion/search application flows.
