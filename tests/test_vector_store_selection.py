from __future__ import annotations

import types
import unittest
from unittest.mock import patch

from knowledge_base.composition import build_vector_store


class VectorStoreSelectionTests(unittest.TestCase):
    def test_build_vector_store_selects_qdrant_backend(self) -> None:
        settings = types.SimpleNamespace(vector_store_backend="qdrant")

        with patch("knowledge_base.composition.QdrantVectorStore") as qdrant_store:
            store = build_vector_store(settings, 4)

        self.assertIs(store, qdrant_store.return_value)
        qdrant_store.assert_called_once_with(settings, 4)

    def test_build_vector_store_defaults_to_milvus_backend(self) -> None:
        settings = types.SimpleNamespace(vector_store_backend="")

        with patch("knowledge_base.composition.MilvusVectorStore") as milvus_store:
            store = build_vector_store(settings, 4)

        self.assertIs(store, milvus_store.return_value)
        milvus_store.assert_called_once_with(settings, 4)

    def test_build_vector_store_rejects_unknown_backend(self) -> None:
        settings = types.SimpleNamespace(vector_store_backend="unknown")

        with self.assertRaisesRegex(ValueError, "Unsupported vector store backend"):
            build_vector_store(settings, 4)


if __name__ == "__main__":
    unittest.main()
