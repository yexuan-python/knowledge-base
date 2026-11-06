from __future__ import annotations

import json
from typing import Any

import pymysql

from .mysql_base import MySQLStoreBase


class BrandProductStore(MySQLStoreBase):
    def count_brand_products_for_delete(self, *, brand_id: int, brand_name: str) -> int:
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT COUNT(*)
                    FROM brand_products
                    WHERE brand_id = %s OR brand_name = %s
                    """,
                    (brand_id, brand_name),
                )
                row = cursor.fetchone()
        return int(row[0] or 0) if row else 0

    def delete_brand_products(self, *, brand_id: int, brand_name: str) -> None:
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    DELETE FROM brand_products
                    WHERE brand_id = %s OR brand_name = %s
                    """,
                    (brand_id, brand_name),
                )

    def upsert_brand_products(
        self,
        *,
        brand_id: int,
        brand_name: str,
        products: list[dict[str, Any]],
    ) -> None:
        with self._get_conn() as conn:
            if hasattr(conn, "begin"):
                conn.begin()
            try:
                with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                    normalized_products = []
                    seen_product_keys: set[str] = set()
                    for product in products:
                        product_values = self._normalize_product_values(
                            brand_id=brand_id,
                            brand_name=brand_name,
                            product=product,
                        )
                        product_code = str(product_values.get("product_code") or "").strip()
                        product_name = str(product_values.get("product_name") or "").strip()
                        product_key = product_code or product_name
                        if not product_name or not product_key or product_key in seen_product_keys:
                            continue
                        seen_product_keys.add(product_key)
                        normalized_products.append(product_values)

                    for product_values in normalized_products:
                        self._upsert_single_brand_product(cursor, product_values)
                if hasattr(conn, "commit"):
                    conn.commit()
            except Exception:
                if hasattr(conn, "rollback"):
                    conn.rollback()
                raise

    def sync_brand_products(
        self,
        *,
        brand_id: int,
        brand_name: str,
        products: list[dict[str, Any]],
    ) -> None:
        """Apply an explicit product snapshot without changing incremental upsert callers."""
        normalized_products = [
            self._normalize_product_values(brand_id=brand_id, brand_name=brand_name, product=product)
            for product in products
        ]
        if any(not product["product_name"] for product in normalized_products):
            raise ValueError("products 中每个产品都必须提供名称")
        product_codes = {product["product_code"] for product in normalized_products if product["product_code"]}
        uncoded_names = {
            product["product_name"].casefold()
            for product in normalized_products if not product["product_code"]
        }
        with self._get_conn() as conn:
            conn.begin()
            try:
                with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                    for product_values in normalized_products:
                        if product_values["product_code"]:
                            self._upsert_single_brand_product(cursor, product_values)
                    cursor.execute(
                        "SELECT id, product_code, product_name FROM brand_products WHERE brand_id = %s FOR UPDATE",
                        (brand_id,),
                    )
                    for existing_product in cursor.fetchall():
                        code = str(existing_product.get("product_code") or "").strip()
                        name = str(existing_product.get("product_name") or "").strip().casefold()
                        if code not in product_codes and name not in uncoded_names:
                            self._delete_product_by_id(cursor, product_id=int(existing_product["id"]))
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    @staticmethod
    def _normalize_product_values(
        *,
        brand_id: int,
        brand_name: str,
        product: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "brand_id": brand_id,
            "brand_name": brand_name,
            "product_code": (product.get("product_code") or "").strip() or None,
            "product_name": (product.get("product_name") or "").strip(),
            "product_alias": (product.get("product_alias") or "").strip() or None,
            "product_description": (product.get("product_description") or "").strip() or None,
            "product_website": (product.get("product_website") or "").strip() or None,
            "product_images_json": (
                json.dumps(product.get("product_images"), ensure_ascii=False)
                if product.get("product_images")
                else None
            ),
            "price_info": (product.get("price_info") or "").strip() or None,
            "coverage_regions_json": (
                json.dumps(product.get("coverage_regions"), ensure_ascii=False)
                if product.get("coverage_regions")
                else None
            ),
            "product_advantages": (product.get("product_advantages") or "").strip() or None,
            "target_scenarios": (product.get("target_scenarios") or "").strip() or None,
            "service_standard": (product.get("service_standard") or "").strip() or None,
            "service_process": (product.get("service_process") or "").strip() or None,
            "cases_and_reputation": (product.get("cases_and_reputation") or "").strip() or None,
            "certification_info": (product.get("certification_info") or "").strip() or None,
            "core_technology": (product.get("core_technology") or "").strip() or None,
            "other_info": (product.get("other_info") or "").strip() or None,
        }

    def _upsert_single_brand_product(self, cursor: Any, product_values: dict[str, Any]) -> None:
        product_code = str(product_values.get("product_code") or "").strip()
        product_name = str(product_values.get("product_name") or "").strip()
        same_name_product = self._get_product_by_brand_and_name(
            cursor,
            brand_id=int(product_values["brand_id"]),
            brand_name=str(product_values["brand_name"]),
            product_name=product_name,
        )
        if product_code:
            product_by_code = self._get_product_by_code(cursor, product_code=product_code)
            if product_by_code is not None:
                if (
                    same_name_product is not None
                    and int(same_name_product["id"]) != int(product_by_code["id"])
                    and not str(same_name_product.get("product_code") or "").strip()
                ):
                    self._delete_product_by_id(cursor, product_id=int(product_by_code["id"]))
                    self._update_product_by_id(
                        cursor,
                        product_id=int(same_name_product["id"]),
                        product_values=product_values,
                    )
                    return
                self._update_product_by_id(
                    cursor,
                    product_id=int(product_by_code["id"]),
                    product_values=product_values,
                )
                return

            if same_name_product is not None:
                same_name_code = str(same_name_product.get("product_code") or "").strip()
                if not same_name_code:
                    self._update_product_by_id(
                        cursor,
                        product_id=int(same_name_product["id"]),
                        product_values=product_values,
                    )
                    return

            self._insert_product(cursor, product_values=product_values)
            return

        if same_name_product is not None:
            self._update_product_by_id(
                cursor,
                product_id=int(same_name_product["id"]),
                product_values=product_values,
            )
            return

        self._insert_product(cursor, product_values=product_values)

    @staticmethod
    def _get_product_by_code(cursor: Any, *, product_code: str) -> dict[str, Any] | None:
        cursor.execute(
            """
            SELECT *
            FROM brand_products
            WHERE product_code = %s
            LIMIT 1
            """,
            (product_code,),
        )
        return cursor.fetchone()

    @staticmethod
    def _get_product_by_brand_and_name(
        cursor: Any,
        *,
        brand_id: int,
        brand_name: str,
        product_name: str,
    ) -> dict[str, Any] | None:
        cursor.execute(
            """
            SELECT *
            FROM brand_products
            WHERE (brand_id = %s OR brand_name = %s)
              AND product_name = %s
            LIMIT 1
            """,
            (brand_id, brand_name, product_name),
        )
        return cursor.fetchone()

    @staticmethod
    def _product_value_tuple(product_values: dict[str, Any]) -> tuple[Any, ...]:
        return (
            product_values["brand_id"],
            product_values["brand_name"],
            product_values["product_code"],
            product_values["product_name"],
            product_values["product_alias"],
            product_values["product_description"],
            product_values["product_website"],
            product_values["product_images_json"],
            product_values["price_info"],
            product_values["coverage_regions_json"],
            product_values["product_advantages"],
            product_values["target_scenarios"],
            product_values["service_standard"],
            product_values["service_process"],
            product_values["cases_and_reputation"],
            product_values["certification_info"],
            product_values["core_technology"],
            product_values["other_info"],
        )

    def _insert_product(self, cursor: Any, *, product_values: dict[str, Any]) -> None:
        cursor.execute(
            """
            INSERT INTO brand_products (
                brand_id,
                brand_name,
                product_code,
                product_name,
                product_alias,
                product_description,
                product_website,
                product_images_json,
                price_info,
                coverage_regions_json,
                product_advantages,
                target_scenarios,
                service_standard,
                service_process,
                cases_and_reputation,
                certification_info,
                core_technology,
                other_info
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            self._product_value_tuple(product_values),
        )

    def _update_product_by_id(
        self,
        cursor: Any,
        *,
        product_id: int,
        product_values: dict[str, Any],
    ) -> None:
        cursor.execute(
            """
            UPDATE brand_products
            SET brand_id = %s,
                brand_name = %s,
                product_code = COALESCE(%s, product_code),
                product_name = %s,
                product_alias = COALESCE(%s, product_alias),
                product_description = COALESCE(%s, product_description),
                product_website = COALESCE(%s, product_website),
                product_images_json = COALESCE(%s, product_images_json),
                price_info = COALESCE(%s, price_info),
                coverage_regions_json = COALESCE(%s, coverage_regions_json),
                product_advantages = COALESCE(%s, product_advantages),
                target_scenarios = COALESCE(%s, target_scenarios),
                service_standard = COALESCE(%s, service_standard),
                service_process = COALESCE(%s, service_process),
                cases_and_reputation = COALESCE(%s, cases_and_reputation),
                certification_info = COALESCE(%s, certification_info),
                core_technology = COALESCE(%s, core_technology),
                other_info = COALESCE(%s, other_info)
            WHERE id = %s
            """,
            (*self._product_value_tuple(product_values), product_id),
        )

    @staticmethod
    def _delete_product_by_id(cursor: Any, *, product_id: int) -> None:
        cursor.execute(
            """
            DELETE FROM brand_products
            WHERE id = %s
            """,
            (product_id,),
        )

    def get_brand_products(self, *, brand_id: int) -> list[dict[str, Any]]:
        with self._get_conn() as conn:
            with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT *
                    FROM brand_products
                    WHERE brand_id = %s
                    ORDER BY product_name ASC
                    """,
                    (brand_id,),
                )
                return list(cursor.fetchall())

    def get_by_product_code(self, *, product_code: str) -> dict[str, Any] | None:
        normalized_product_code = str(product_code or "").strip()
        if not normalized_product_code:
            return None
        with self._get_conn() as conn:
            with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT bp.*, b.brand_code
                    FROM brand_products bp
                    LEFT JOIN brands b ON b.id = bp.brand_id
                    WHERE bp.product_code = %s
                    LIMIT 1
                    """,
                    (normalized_product_code,),
                )
                row = cursor.fetchone()
        return row or None
