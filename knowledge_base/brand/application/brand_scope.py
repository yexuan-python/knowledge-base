from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class BrandScope:
    brand_id: int | None = None
    brand_code: str | None = None
    brand_name: str | None = None
    product_code: str | None = None
    product_name: str | None = None
    brand: dict[str, Any] | None = None
    product: dict[str, Any] | None = None


def resolve_brand_scope_from_codes(
    deps: Any,
    *,
    brand_code: str | None = None,
    brand_name: str | None = None,
    category: str | None = None,
    product_code: str | None = None,
) -> BrandScope:
    requested_brand_code = str(brand_code or "").strip()
    requested_brand_name = str(brand_name or category or "").strip()
    requested_product_code = str(product_code or "").strip()
    brands = getattr(deps, "brands", None)

    if requested_product_code:
        product = _get_product_by_code(deps, product_code=requested_product_code)
        if not product:
            raise ValueError("product_code 对应的产品不存在")

        product_brand_id = _normalize_int(product.get("brand_id"))
        product_brand_code = str(product.get("brand_code") or "").strip()
        product_brand_name = str(product.get("brand_name") or "").strip()
        brand = None

        if brands is not None:
            if requested_brand_code and hasattr(brands, "get_brand_by_code"):
                brand = brands.get_brand_by_code(requested_brand_code)
                if brand and product_brand_id is not None and _normalize_int(brand.get("id")) != product_brand_id:
                    raise ValueError("product_code 不属于指定 brand_code")
            elif product_brand_id is not None and hasattr(brands, "get_brand_by_id"):
                brand = brands.get_brand_by_id(product_brand_id)
            elif product_brand_code and hasattr(brands, "get_brand_by_code"):
                brand = brands.get_brand_by_code(product_brand_code)

        if requested_brand_code and product_brand_code and requested_brand_code != product_brand_code:
            raise ValueError("product_code 不属于指定 brand_code")

        if brand:
            product_brand_id = _normalize_int(brand.get("id")) or product_brand_id
            product_brand_code = str(brand.get("brand_code") or product_brand_code).strip()
            product_brand_name = str(brand.get("brand_name") or product_brand_name).strip()

        return BrandScope(
            brand_id=product_brand_id,
            brand_code=product_brand_code or requested_brand_code or None,
            brand_name=product_brand_name or requested_brand_name or None,
            product_code=requested_product_code,
            product_name=str(product.get("product_name") or "").strip() or None,
            brand=brand,
            product=product,
        )

    if requested_brand_code and brands is not None and hasattr(brands, "get_brand_by_code"):
        brand = brands.get_brand_by_code(requested_brand_code)
        if brand:
            return BrandScope(
                brand_id=_normalize_int(brand.get("id")),
                brand_code=str(brand.get("brand_code") or requested_brand_code).strip() or None,
                brand_name=str(brand.get("brand_name") or requested_brand_name).strip() or None,
                brand=brand,
            )

    return BrandScope(
        brand_code=requested_brand_code or None,
        brand_name=requested_brand_name or None,
    )


def _get_product_by_code(deps: Any, *, product_code: str) -> dict[str, Any] | None:
    brand_products = getattr(deps, "brand_products", None)
    if brand_products is None or not hasattr(brand_products, "get_by_product_code"):
        return None
    return brand_products.get_by_product_code(product_code=product_code)


def _normalize_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
