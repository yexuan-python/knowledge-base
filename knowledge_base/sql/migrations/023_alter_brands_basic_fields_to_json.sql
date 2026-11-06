UPDATE brands
SET customer_service_hotline = CASE
        WHEN customer_service_hotline IS NULL THEN NULL
        WHEN TRIM(customer_service_hotline) = '' THEN JSON_ARRAY()
        WHEN JSON_VALID(customer_service_hotline)
             AND JSON_TYPE(CAST(customer_service_hotline AS JSON)) = 'ARRAY' THEN CAST(customer_service_hotline AS JSON)
        WHEN JSON_VALID(customer_service_hotline) THEN JSON_ARRAY(
            JSON_UNQUOTE(JSON_EXTRACT(CAST(customer_service_hotline AS JSON), '$'))
        )
        ELSE JSON_ARRAY(TRIM(customer_service_hotline))
    END,
    positioning = CASE
        WHEN positioning IS NULL THEN NULL
        WHEN TRIM(positioning) = '' THEN JSON_ARRAY()
        WHEN JSON_VALID(positioning)
             AND JSON_TYPE(CAST(positioning AS JSON)) = 'ARRAY' THEN CAST(positioning AS JSON)
        WHEN JSON_VALID(positioning) THEN JSON_ARRAY(
            JSON_UNQUOTE(JSON_EXTRACT(CAST(positioning AS JSON), '$'))
        )
        ELSE JSON_ARRAY(TRIM(positioning))
    END,
    advantages = CASE
        WHEN advantages IS NULL THEN NULL
        WHEN TRIM(advantages) = '' THEN JSON_ARRAY()
        WHEN JSON_VALID(advantages)
             AND JSON_TYPE(CAST(advantages AS JSON)) = 'ARRAY' THEN CAST(advantages AS JSON)
        WHEN JSON_VALID(advantages) THEN JSON_ARRAY(
            JSON_UNQUOTE(JSON_EXTRACT(CAST(advantages AS JSON), '$'))
        )
        ELSE JSON_ARRAY(TRIM(advantages))
    END,
    mission = CASE
        WHEN mission IS NULL THEN NULL
        WHEN TRIM(mission) = '' THEN JSON_ARRAY()
        WHEN JSON_VALID(mission)
             AND JSON_TYPE(CAST(mission AS JSON)) = 'ARRAY' THEN CAST(mission AS JSON)
        WHEN JSON_VALID(mission) THEN JSON_ARRAY(
            JSON_UNQUOTE(JSON_EXTRACT(CAST(mission AS JSON), '$'))
        )
        ELSE JSON_ARRAY(TRIM(mission))
    END,
    vision = CASE
        WHEN vision IS NULL THEN NULL
        WHEN TRIM(vision) = '' THEN JSON_ARRAY()
        WHEN JSON_VALID(vision)
             AND JSON_TYPE(CAST(vision AS JSON)) = 'ARRAY' THEN CAST(vision AS JSON)
        WHEN JSON_VALID(vision) THEN JSON_ARRAY(
            JSON_UNQUOTE(JSON_EXTRACT(CAST(vision AS JSON), '$'))
        )
        ELSE JSON_ARRAY(TRIM(vision))
    END;
