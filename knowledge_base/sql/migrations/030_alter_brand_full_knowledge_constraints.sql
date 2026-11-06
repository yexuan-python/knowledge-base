ALTER TABLE brand_full_knowledge_files
    DROP INDEX uk_brand_full_knowledge_version,
    DROP INDEX uk_brand_full_knowledge_task,
    ADD UNIQUE KEY uk_brand_full_knowledge_version_revision (
        brand_code,
        version_no,
        knowledge_date,
        revision_no
    ),
    ADD UNIQUE KEY uk_brand_full_knowledge_task_file (
        brand_code,
        source_task_id,
        file_name
    );
