from __future__ import annotations

from pathlib import Path
from typing import Any, Awaitable, Callable
from uuid import uuid4

from knowledge_base.brand.schemas import BrandUploadRequest
from knowledge_base.shared.utils import normalize_upload_metadata, resolve_registry_category
from knowledge_base.upload_task.schemas import UploadTaskCreateResponse


class BrandUploadTaskEnqueuer:
    def __init__(
        self,
        *,
        dependencies: Any,
        lifecycle: Any,
        normalize_int: Callable[[Any], int | None],
        normalize_websites: Callable[[Any], list[str]],
        serialize_brand_competitors: Callable[[Any], list[dict[str, str | None]]],
        serialize_websites: Callable[[Any], str | None],
        schedule_upload_task: Callable[[str], Awaitable[None]],
    ) -> None:
        self._deps = dependencies
        self._lifecycle = lifecycle
        self._normalize_int = normalize_int
        self._normalize_websites = normalize_websites
        self._serialize_brand_competitors = serialize_brand_competitors
        self._serialize_websites = serialize_websites
        self._schedule_upload_task = schedule_upload_task

    async def enqueue_brand_upload_task(self, request: BrandUploadRequest) -> UploadTaskCreateResponse:
        brand_name = request.brand_name.strip()
        if not brand_name:
            raise ValueError("brand_name 不能为空")
        brand_code = (request.brand_code or "").strip() or None
        brand_alias = (request.brand_alias or "").strip() or None
        industry_id = self._normalize_int(request.industry_id)
        industry_code = (request.industry_code or "").strip() or None
        industry_name = (request.industry_name or "").strip() or None
        brand_enterprise_entity = (request.enterprise_subject or "").strip() or None
        business_license_image_path = (request.business_license_url or "").strip() or None

        attachments = [
            item for item in request.attachments if item.name.strip() and item.url.strip()
        ]

        task_id = str(uuid4())

        competitor_names = [
            item.name.strip()
            for item in request.competitors
            if item.name.strip()
        ]
        structured_competitors = self._serialize_brand_competitors(request.competitors)
        intro = (request.intro or "").strip()
        structured_products = []
        for product in request.products:
            product_name = (product.name or "").strip()
            if not product_name:
                continue
            structured_product = {
                "product_name": product_name,
                "product_alias": (product.product_alias or "").strip() or None,
                "product_description": (product.product_description or "").strip() or None,
                "product_website": (product.product_link or "").strip() or None,
                "product_images": [item.strip() for item in (product.product_images or []) if item.strip()],
                "competitors": self._serialize_brand_competitors(product.competitors),
            }
            product_code = (getattr(product, "product_code", None) or "").strip()
            if product_code:
                structured_product["product_code"] = product_code
            structured_products.append(structured_product)
        metadata: dict[str, Any] = {
            "brand_name": brand_name,
            "category": brand_name,
            "brand_callback_enabled": True,
        }
        if brand_code:
            metadata["brand_code"] = brand_code
        if request.force_reingest:
            metadata["force_reingest"] = True
        if brand_alias:
            metadata["brand_alias"] = brand_alias
        if industry_id is not None:
            metadata["industry_id"] = industry_id
        if industry_code:
            metadata["industry_code"] = industry_code
        if industry_name:
            metadata["industry_name"] = industry_name
        if request.brand_logo:
            metadata["brand_logo"] = request.brand_logo
        normalized_websites = self._normalize_websites(request.website)
        if normalized_websites:
            metadata["website"] = normalized_websites
        if brand_enterprise_entity:
            metadata["brand_enterprise_entity"] = brand_enterprise_entity
        if business_license_image_path:
            metadata["business_license_image_path"] = business_license_image_path
        if intro:
            metadata["intro"] = intro
        if request.email:
            metadata["email"] = request.email
        if competitor_names:
            metadata["competitors"] = competitor_names

        staged_files: list[dict[str, Any]] = []
        reserved_registry_files: list[dict[str, Any]] = []
        file_metadata_by_index: dict[str, dict[str, Any]] = {}

        try:
            if industry_id is not None and (industry_code or industry_name):
                self._deps.industries.upsert_industry(
                    industry_id=industry_id,
                    code=industry_code,
                    name=industry_name,
                )

            brand_id = self._deps.brands.upsert_brand(
                brand_code=brand_code,
                brand_name=brand_name,
                brand_alias=brand_alias,
                brand_logo=request.brand_logo,
                website=self._serialize_websites(request.website),
                brand_enterprise_entity=brand_enterprise_entity,
                business_license_image_path=business_license_image_path,
                industry_id=industry_id,
                intro=intro,
                email=request.email,
                competitors=competitor_names or None,
            )

            if structured_products:
                self._deps.brand_products.upsert_brand_products(
                    brand_id=brand_id,
                    brand_name=brand_name,
                    products=structured_products,
                )

            for index, item in enumerate(attachments):
                filename = Path(item.name.strip()).name or f"attachment-{index + 1}"
                staged = {
                    "file_index": len(staged_files),
                    "original_filename": filename,
                    "file_role": "attachment",
                    "stored_path": "",
                    "file_size": None,
                    "file_hash": None,
                }
                staged_files.append(staged)
                file_metadata_by_index[str(staged["file_index"])] = {
                    "source_url": item.url.strip(),
                }

            next_index = len(staged_files)
            for product_index, product in enumerate(request.products, start=1):
                description = (product.product_description or "").strip()
                product_competitors = self._serialize_brand_competitors(product.competitors)

                product_name = (product.name or "").strip() or f"product-{product_index}"
                safe_product_name = Path(product_name).name or f"product-{product_index}"

                product_attachments = [
                    item for item in product.attachments if item.name.strip() and item.url.strip()
                ]
                for item in product_attachments:
                    filename = Path(item.name.strip()).name or f"{safe_product_name}-attachment"
                    staged = {
                        "file_index": next_index,
                        "original_filename": filename,
                        "file_role": "attachment",
                        "stored_path": "",
                        "file_size": None,
                        "file_hash": None,
                    }
                    staged_files.append(staged)
                    product_file_metadata = {
                        "source_url": item.url.strip(),
                        "subcategory": product_name,
                        "product_name": product_name,
                        "product_alias": (product.product_alias or "").strip() or None,
                        "product_images": [image.strip() for image in (product.product_images or []) if image.strip()],
                        "product_link": (product.product_link or "").strip() or None,
                        "product_description": description or None,
                        "product_competitors": product_competitors or None,
                    }
                    product_code = (getattr(product, "product_code", None) or "").strip()
                    if product_code:
                        product_file_metadata["product_code"] = product_code
                    file_metadata_by_index[str(next_index)] = product_file_metadata
                    next_index += 1

            registry_category = resolve_registry_category(brand_name)
            reserved_files = [item for item in staged_files if item.get("file_hash")]
            reserve_result = self._deps.document_registry.reserve_document_uploads(
                category=registry_category,
                task_id=task_id,
                files=reserved_files,
                allow_partial=True,
            )
            reserved_registry_files = reserve_result["reserved_files"]
            for item in reserve_result["duplicate_files"]:
                item["status"] = "failed"
                item["error_message"] = "发现相同文件已存在，无法上传"
                Path(item["stored_path"]).unlink(missing_ok=True)
            metadata["_task_payload"] = {
                "file_metadata_by_index": file_metadata_by_index,
                "requested_products": structured_products,
                "requested_competitors": structured_competitors,
            }
            prepared_metadata = normalize_upload_metadata(metadata)
            self._deps.upload_tasks.create_upload_task(
                task_id=task_id,
                task_type="brand_upload",
                metadata=prepared_metadata,
                chunk_size=None,
                chunk_overlap=None,
                files=staged_files,
            )
            await self._deps.notify_failed_upload_files(task_id)
        except Exception:
            registry_category = resolve_registry_category(brand_name)
            for item in reserved_registry_files:
                self._deps.document_registry.release_document_upload(
                    category=registry_category,
                    file_hash=item["file_hash"],
                )
            raise

        if staged_files:
            await self._schedule_upload_task(task_id)
            response_status = "queued"
            response_message = "品牌资料已提交成功，后台任务正在排队处理"
        else:
            self._lifecycle.complete_empty_task(task_id)
            completion_check_delay_seconds = 0
            response_status = "completed"
            response_message = "品牌资料已提交成功，后台正在生成品牌 AI 知识库"
        if not staged_files:
            self._deps.schedule_delayed_completion_check(
                task_id,
                delay_seconds=completion_check_delay_seconds,
            )
        return UploadTaskCreateResponse(
            task_id=task_id,
            status=response_status,
            file_count=len(staged_files),
            message=response_message,
        )
