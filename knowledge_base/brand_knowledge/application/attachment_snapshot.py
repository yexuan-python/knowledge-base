from __future__ import annotations

from knowledge_base.brand_knowledge.application.attachment_snapshot_context import (
    AttachmentDraftSnapshotContextMixin,
)
from knowledge_base.brand_knowledge.application.attachment_snapshot_conversion import (
    AttachmentDraftSnapshotConversionMixin,
)
from knowledge_base.brand_knowledge.application.attachment_snapshot_normalization import (
    AttachmentDraftSnapshotNormalizationMixin,
)
from knowledge_base.brand_knowledge.application.attachment_snapshot_other_info import (
    AttachmentDraftSnapshotOtherInfoMixin,
)
from knowledge_base.brand_knowledge.application.attachment_snapshot_payload import (
    AttachmentDraftSnapshotPayloadMixin,
)


class AttachmentDraftSnapshotMixin(
    AttachmentDraftSnapshotContextMixin,
    AttachmentDraftSnapshotNormalizationMixin,
    AttachmentDraftSnapshotOtherInfoMixin,
    AttachmentDraftSnapshotConversionMixin,
    AttachmentDraftSnapshotPayloadMixin,
):
    """Compose snapshot responsibilities from focused mixins."""

