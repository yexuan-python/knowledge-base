# Qdrant Vector Store Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Qdrant as an optional vector-store backend selected by environment configuration.

**Architecture:** Keep the existing store contract intact. Add `QdrantVectorStore`, extend settings, and choose between `MilvusVectorStore` and `QdrantVectorStore` in composition.

**Tech Stack:** Python 3.12, FastAPI service code, `qdrant-client`, `unittest`.

**Spec:** `docs/superpowers/specs/2026-09-05-qdrant-vector-store-design.md`

## Global Constraints

- `KB_VECTOR_STORE` defaults to `milvus`.
- Qdrant support must not require upper application layers to know which vector database is active.
- Existing Milvus behavior remains available for rollback.
- Tests must exercise store selection and Qdrant filter/result normalization without requiring a live Qdrant server.

---

### Task 1: Configuration And Backend Selection

**Files:**
- Modify: `knowledge_base/infrastructure/settings.py`
- Modify: `knowledge_base/composition.py`
- Test: `tests/test_vector_store_selection.py`

**Interfaces:**
- Produces: settings fields `vector_store_backend`, `qdrant_url`, `qdrant_api_key`, `qdrant_collection_name`, `qdrant_facts_collection_name`, `qdrant_on_disk_vectors`, `qdrant_timeout_seconds`.
- Produces: `build_vector_store(settings, dimension)` returning the selected vector store instance.

- [ ] **Step 1: Write failing tests**

```python
def test_build_vector_store_selects_qdrant_backend():
    settings = types.SimpleNamespace(vector_store_backend="qdrant")
    store = build_vector_store(settings, 3)
    self.assertIsInstance(store, QdrantVectorStore)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m unittest tests.test_vector_store_selection`
Expected: FAIL because `build_vector_store` or `QdrantVectorStore` is missing.

- [ ] **Step 3: Implement configuration and selection**

Add the settings fields and a `build_vector_store()` helper. Keep `milvus` as the default.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m unittest tests.test_vector_store_selection`
Expected: PASS.

### Task 2: Qdrant Store Contract

**Files:**
- Create: `knowledge_base/infrastructure/qdrant_store.py`
- Modify: `knowledge_base/infrastructure/__init__.py`
- Test: `tests/test_qdrant_store.py`

**Interfaces:**
- Consumes: settings fields from Task 1.
- Produces: `QdrantVectorStore` with methods matching `MilvusVectorStore`.

- [ ] **Step 1: Write failing tests**

```python
def test_search_builds_document_and_source_type_filter():
    client = _FakeQdrantClient()
    store = QdrantVectorStore.__new__(QdrantVectorStore)
    store._client = client
    store._collection_name = "documents"
    result = store.search(query_vector=[0.1, 0.2], top_k=3, document_ids=["doc-1"], source_types=["text"])
    self.assertEqual(result[0]["document_id"], "doc-1")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m unittest tests.test_qdrant_store`
Expected: FAIL because `QdrantVectorStore` is not implemented.

- [ ] **Step 3: Implement store methods**

Implement collection creation, insert/upsert, search, get, delete, and rename operations with Qdrant filters and result normalization.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run python -m unittest tests.test_qdrant_store tests.test_vector_store_selection`
Expected: PASS.

### Task 3: Dependencies And Docs

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `.env.example`
- Modify: `README.md`

**Interfaces:**
- Consumes: Qdrant backend settings.
- Produces: documented deployment and environment values for Qdrant.

- [ ] **Step 1: Add dependency**

Add `qdrant-client` to project dependencies and refresh the lockfile.

- [ ] **Step 2: Document configuration**

Add Qdrant Docker run command and `KB_VECTOR_STORE=qdrant` settings.

- [ ] **Step 3: Verify**

Run: `uv run python -m unittest tests.test_qdrant_store tests.test_vector_store_selection tests.test_search_application_service tests.test_milvus_store_filters`
Expected: PASS.
