from __future__ import annotations

import unittest

from knowledge_base.brand import knowledge_extraction as brand_knowledge_extraction


class BrandKnowledgeExtractionMergeTests(unittest.TestCase):
    def test_merge_official_media_matrix_allows_missing_account_id(self) -> None:
        merged = brand_knowledge_extraction._merge_official_media_matrix(
            [],
            [
                {
                    "media_platform": "微信公众号",
                    "account_name": "品牌服务号",
                    "account_id": None,
                    "is_official": "是",
                    "related_products": ["200001"],
                    "other_info": ["新品发布"],
                }
            ],
        )

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["media_platform"], "微信公众号")
        self.assertEqual(merged[0]["account_name"], "品牌服务号")
        self.assertIsNone(merged[0]["account_id"])

    def test_merge_official_malls_allows_missing_store_name_and_platform(self) -> None:
        merged = brand_knowledge_extraction._merge_official_malls(
            [],
            [
                {
                    "store_name": None,
                    "platform": None,
                    "homepage_urls": ["https://mall.example.com"],
                    "main_categories": ["智能汽车"],
                    "advantages": ["官方正品"],
                    "related_products": [1001],
                    "other_info": ["支持售后咨询"],
                }
            ],
        )

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["homepage_urls"], ["https://mall.example.com"])
        self.assertIsNone(merged[0]["store_name"])
        self.assertIsNone(merged[0]["platform"])

    def test_merge_requested_competitors_allows_new_extracted_competitors(self) -> None:
        merged = brand_knowledge_extraction._merge_requested_competitors_with_extracted(
            [
                {
                    "name": "竞品A",
                    "website": "https://competitor-a.example.com",
                }
            ],
            [
                {
                    "name": "竞品A",
                    "competitors_description": "竞品A补充介绍",
                    "website": "",
                },
                {
                    "name": "竞品B",
                    "competitors_description": "附件发现的新竞品",
                    "website": "https://competitor-b.example.com",
                },
            ],
        )

        self.assertEqual([item["name"] for item in merged], ["竞品A", "竞品B"])
        self.assertEqual(merged[0]["website"], "https://competitor-a.example.com")
        self.assertEqual(merged[0]["competitors_description"], "竞品A补充介绍")
        self.assertEqual(merged[1]["competitors_description"], "附件发现的新竞品")


if __name__ == "__main__":
    unittest.main()
