export type SearchResultMetadata = {
  brand_id?: string | number | null;
  brand_code?: string | null;
  brand_name?: string | null;
  kb_version?: string | null;
  section_title?: string | null;
  source_url?: string | null;
  content_hash?: string | null;
};

export type SearchResultItem = {
  chunk_id?: string | null;
  content: string;
  score?: number | null;
  brand_name?: string | null;
  category?: string | null;
  metadata?: SearchResultMetadata | null;
};

export type SearchResponse = {
  code: number;
  message: string;
  data: SearchResultItem[];
};

export type BrandFactsResponse = {
  brand_code?: string | null;
  brand_name?: string | null;
  category?: string | null;
  query?: string | null;
  facts: Array<Record<string, unknown> | string>;
};

export type CategoryFactsResponse = BrandFactsResponse;
