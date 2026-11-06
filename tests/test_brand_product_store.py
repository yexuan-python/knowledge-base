from __future__ import annotations

import copy
import importlib.util
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch


def _load_brand_product_store_class():
    module_path = Path(__file__).resolve().parent.parent / "knowledge_base" / "stores" / "brand_product_store.py"
    spec = importlib.util.spec_from_file_location("knowledge_base.stores._brand_product_store_real", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load BrandProductStore module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.BrandProductStore


BrandProductStore = _load_brand_product_store_class()


_PRODUCT_COLUMNS = [
    "brand_id",
    "brand_name",
    "product_code",
    "product_name",
    "product_alias",
    "product_description",
    "product_website",
    "product_images_json",
    "price_info",
    "coverage_regions_json",
    "product_advantages",
    "target_scenarios",
    "service_standard",
    "service_process",
    "cases_and_reputation",
    "certification_info",
    "core_technology",
    "other_info",
]


class _FakeCursor:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self._result: Any = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        normalized_sql = " ".join(sql.split()).lower()
        if normalized_sql.startswith("select") and "where brand_id = %s" in normalized_sql:
            self._result = [row for row in self.rows if row.get("brand_id") == params[0]]
            return
        if "where product_code = %s" in normalized_sql:
            product_code = params[0]
            self._result = self._find_by_product_code(product_code)
            return
        if "where (brand_id = %s or brand_name = %s) and product_name = %s" in normalized_sql:
            brand_id, brand_name, product_name = params[:3]
            exclude_id = params[3] if len(params) > 3 else None
            self._result = self._find_by_brand_and_name(
                brand_id=brand_id,
                brand_name=brand_name,
                product_name=product_name,
                exclude_id=exclude_id,
            )
            return
        if normalized_sql.startswith("insert into brand_products"):
            self._insert(dict(zip(_PRODUCT_COLUMNS, params, strict=True)))
            self._result = None
            return
        if normalized_sql.startswith("update brand_products"):
            values = dict(zip(_PRODUCT_COLUMNS, params[:-1], strict=True))
            self._update_by_id(int(params[-1]), values)
            self._result = None
            return
        if normalized_sql.startswith("delete from brand_products where id = %s"):
            row_id = int(params[0])
            self.rows[:] = [row for row in self.rows if int(row["id"]) != row_id]
            self._result = None
            return
        raise AssertionError(f"Unexpected SQL: {sql}")

    def executemany(self, sql: str, values: list[tuple[Any, ...]]) -> None:
        # Simulate the old MySQL ON DUPLICATE KEY behavior so regression tests
        # fail before BrandProductStore is changed.
        for params in values:
            next_values = dict(zip(_PRODUCT_COLUMNS, params, strict=True))
            existing = (
                self._find_by_product_code(next_values["product_code"])
                if next_values.get("product_code")
                else None
            )
            if existing is None:
                existing = self._find_by_brand_and_name(
                    brand_id=next_values["brand_id"],
                    brand_name=next_values["brand_name"],
                    product_name=next_values["product_name"],
                )
            if existing is None:
                self._insert(next_values)
                continue
            existing["brand_id"] = existing.get("brand_id") or next_values["brand_id"]
            for key, value in next_values.items():
                if key == "brand_id":
                    continue
                if value is not None:
                    existing[key] = value

    def fetchone(self):
        return copy.deepcopy(self._result) if self._result is not None else None

    def fetchall(self):
        return copy.deepcopy(self._result)

    def _find_by_product_code(self, product_code: Any) -> dict[str, Any] | None:
        normalized_product_code = str(product_code or "").strip()
        for row in self.rows:
            if str(row.get("product_code") or "").strip() == normalized_product_code:
                return row
        return None

    def _find_by_brand_and_name(
        self,
        *,
        brand_id: Any,
        brand_name: Any,
        product_name: Any,
        exclude_id: Any = None,
    ) -> dict[str, Any] | None:
        normalized_product_name = str(product_name or "").strip()
        normalized_brand_name = str(brand_name or "").strip()
        for row in self.rows:
            if exclude_id is not None and int(row["id"]) == int(exclude_id):
                continue
            same_brand = row.get("brand_id") == brand_id or str(row.get("brand_name") or "").strip() == normalized_brand_name
            same_name = str(row.get("product_name") or "").strip() == normalized_product_name
            if same_brand and same_name:
                return row
        return None

    def _insert(self, values: dict[str, Any]) -> None:
        row = {"id": max([int(item["id"]) for item in self.rows] or [0]) + 1}
        row.update(values)
        self.rows.append(row)

    def _update_by_id(self, row_id: int, values: dict[str, Any]) -> None:
        row = next(item for item in self.rows if int(item["id"]) == row_id)
        for key, value in values.items():
            if key in {"brand_id", "brand_name", "product_code", "product_name"}:
                if value is not None:
                    row[key] = value
                continue
            if value is not None:
                row[key] = value


class _FakeConnection:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self, *args, **kwargs):
        return _FakeCursor(self.rows)

    def begin(self):
        self.snapshot = copy.deepcopy(self.rows)

    def commit(self):
        pass

    def rollback(self):
        self.rows[:] = self.snapshot


def _build_store(rows: list[dict[str, Any]]) -> BrandProductStore:
    store = object.__new__(BrandProductStore)
    store._get_conn = lambda: _FakeConnection(rows)  # type: ignore[attr-defined]
    return store


class BrandProductStoreTests(unittest.TestCase):
    def test_sync_removes_missing_products_and_preserves_other_brands_and_retained_ids(self) -> None:
        rows = [
            {"id": 1, "brand_id": 1, "brand_name": "示例品牌", "product_code": "A", "product_name": "产品A"},
            {"id": 2, "brand_id": 1, "brand_name": "示例品牌", "product_code": "B", "product_name": "产品B"},
            {"id": 3, "brand_id": 2, "brand_name": "其他品牌", "product_code": "C", "product_name": "产品C"},
        ]
        store = _build_store(rows)
        store.sync_brand_products(
            brand_id=1, brand_name="示例品牌",
            products=[{"product_code": "A", "product_name": "产品A", "product_description": "新描述"}],
        )
        self.assertEqual([row["id"] for row in rows], [1, 3])
        self.assertEqual(rows[0]["product_description"], "新描述")
        store.sync_brand_products(brand_id=1, brand_name="示例品牌", products=[])
        self.assertEqual([row["id"] for row in rows], [3])

    def test_sync_matches_codes_even_when_product_names_are_identical(self) -> None:
        rows = [
            {"id": 1, "brand_id": 1, "brand_name": "示例品牌", "product_code": "A", "product_name": "同名产品"},
            {"id": 2, "brand_id": 1, "brand_name": "示例品牌", "product_code": "B", "product_name": "同名产品"},
        ]
        _build_store(rows).sync_brand_products(
            brand_id=1, brand_name="示例品牌", products=[{"product_code": "A", "product_name": "同名产品"}],
        )
        self.assertEqual([row["product_code"] for row in rows], ["A"])

    def test_sync_retains_existing_product_named_without_code_but_does_not_insert_uncoded_products(self) -> None:
        rows = [{"id": 1, "brand_id": 1, "brand_name": "示例品牌", "product_code": "A", "product_name": "产品A"}]
        _build_store(rows).sync_brand_products(
            brand_id=1, brand_name="示例品牌",
            products=[{"product_name": "产品A"}, {"product_name": "无编码新产品"}],
        )
        self.assertEqual([row["id"] for row in rows], [1])

    def test_sync_rolls_back_upsert_when_deletion_fails(self) -> None:
        rows = [
            {"id": 1, "brand_id": 1, "brand_name": "示例品牌", "product_code": "A", "product_name": "产品A", "product_description": "旧描述"},
            {"id": 2, "brand_id": 1, "brand_name": "示例品牌", "product_code": "B", "product_name": "产品B"},
        ]
        original_rows = copy.deepcopy(rows)
        store = _build_store(rows)
        with patch.object(store, "_delete_product_by_id", side_effect=RuntimeError("delete failed")):
            with self.assertRaisesRegex(RuntimeError, "delete failed"):
                store.sync_brand_products(
                    brand_id=1, brand_name="示例品牌",
                    products=[{"product_code": "A", "product_name": "产品A", "product_description": "新描述"}],
                )
        self.assertEqual(rows, original_rows)

    def test_product_code_upsert_migrates_existing_product_to_latest_brand(self) -> None:
        rows = [
            {
                "id": 1,
                "brand_id": 1298,
                "brand_name": "御温泉渡假村",
                "product_code": "200204",
                "product_name": "大餐庙会",
                "product_description": "旧描述",
            }
        ]
        store = _build_store(rows)

        store.upsert_brand_products(
            brand_id=2000,
            brand_name="另一个品牌",
            products=[
                {
                    "product_code": "200204",
                    "product_name": "大餐庙会",
                    "product_description": "新描述",
                }
            ],
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["brand_id"], 2000)
        self.assertEqual(rows[0]["brand_name"], "另一个品牌")
        self.assertEqual(rows[0]["product_description"], "新描述")

    def test_product_code_upsert_backfills_same_brand_product_without_code(self) -> None:
        rows = [
            {
                "id": 1,
                "brand_id": 2000,
                "brand_name": "另一个品牌",
                "product_code": None,
                "product_name": "大餐庙会",
            }
        ]
        store = _build_store(rows)

        store.upsert_brand_products(
            brand_id=2000,
            brand_name="另一个品牌",
            products=[
                {
                    "product_code": "200204",
                    "product_name": "大餐庙会",
                }
            ],
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["product_code"], "200204")

    def test_product_code_upsert_inserts_same_brand_same_name_different_code(self) -> None:
        rows = [
            {
                "id": 1,
                "brand_id": 2000,
                "brand_name": "另一个品牌",
                "product_code": "300999",
                "product_name": "大餐庙会",
            }
        ]
        store = _build_store(rows)

        store.upsert_brand_products(
            brand_id=2000,
            brand_name="另一个品牌",
            products=[
                {
                    "product_code": "200204",
                    "product_name": "大餐庙会",
                    "product_description": "新描述",
                }
            ],
        )

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["product_code"], "300999")
        self.assertEqual(rows[1]["product_code"], "200204")
        self.assertEqual(rows[1]["product_name"], "大餐庙会")
        self.assertEqual(rows[1]["product_description"], "新描述")

    def test_product_code_upsert_inserts_duplicate_name_with_different_code_in_same_payload(self) -> None:
        rows: list[dict[str, Any]] = []
        store = _build_store(rows)

        store.upsert_brand_products(
            brand_id=2000,
            brand_name="另一个品牌",
            products=[
                {
                    "product_code": "300999",
                    "product_name": "大餐庙会",
                    "product_description": "先入库",
                },
                {
                    "product_code": "200204",
                    "product_name": "大餐庙会",
                    "product_description": "也应入库",
                },
            ],
        )

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["product_code"], "300999")
        self.assertEqual(rows[0]["product_description"], "先入库")
        self.assertEqual(rows[1]["product_code"], "200204")
        self.assertEqual(rows[1]["product_description"], "也应入库")

    def test_product_code_upsert_merges_migrated_product_into_target_brand_placeholder(self) -> None:
        rows = [
            {
                "id": 1,
                "brand_id": 1298,
                "brand_name": "御温泉渡假村",
                "product_code": "200204",
                "product_name": "大餐庙会",
            },
            {
                "id": 2,
                "brand_id": 2000,
                "brand_name": "另一个品牌",
                "product_code": None,
                "product_name": "大餐庙会",
            },
        ]
        store = _build_store(rows)

        store.upsert_brand_products(
            brand_id=2000,
            brand_name="另一个品牌",
            products=[
                {
                    "product_code": "200204",
                    "product_name": "大餐庙会",
                    "product_alias": "新别名",
                }
            ],
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], 2)
        self.assertEqual(rows[0]["brand_id"], 2000)
        self.assertEqual(rows[0]["product_code"], "200204")
        self.assertEqual(rows[0]["product_alias"], "新别名")


if __name__ == "__main__":
    unittest.main()
