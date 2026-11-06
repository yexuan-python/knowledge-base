import { forwardRef, useEffect, useId, useState } from "react";

import { getBrands } from "../api/knowledgeBaseApi";
import type { BrandListItem } from "../types";

type BrandSearchSelectProps = {
  brands: BrandListItem[];
  selectedBrand: BrandListItem | null;
  onSelect: (brand: BrandListItem | null) => void;
  disabled?: boolean;
  loading?: boolean;
  inputId?: string;
};

function formatBrandOption(brand: BrandListItem): string {
  const brandCode = brand.brand_code?.trim();
  return `${brand.brand_name}${brandCode ? ` · ${brandCode}` : " · 缺少 brand_code"}`;
}

const BrandSearchSelect = forwardRef<HTMLInputElement, BrandSearchSelectProps>(function BrandSearchSelect(
  { brands, selectedBrand, onSelect, disabled = false, loading = false, inputId },
  ref,
) {
  const listId = useId();
  const [search, setSearch] = useState("");
  const [options, setOptions] = useState<BrandListItem[]>([]);
  const [open, setOpen] = useState(false);
  const [searchLoading, setSearchLoading] = useState(false);
  const [searchError, setSearchError] = useState("");
  const [activeOption, setActiveOption] = useState(-1);

  useEffect(() => {
    if (!open || disabled) {
      return;
    }
    const keyword = search.trim();
    if (!keyword) {
      setOptions(brands);
      setSearchLoading(false);
      setSearchError("");
      return;
    }

    let cancelled = false;
    setOptions([]);
    setSearchLoading(true);
    setSearchError("");
    const timer = window.setTimeout(() => {
      void getBrands(keyword)
        .then((response) => {
          if (!cancelled) {
            setOptions(response.brands);
          }
        })
        .catch((error: unknown) => {
          if (!cancelled) {
            setSearchError(error instanceof Error ? error.message : "品牌搜索失败，请重试");
          }
        })
        .finally(() => {
          if (!cancelled) {
            setSearchLoading(false);
          }
        });
    }, 250);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [open, disabled, search, brands]);

  function selectBrand(brand: BrandListItem | null) {
    setOpen(false);
    setSearch("");
    setActiveOption(-1);
    onSelect(brand);
  }

  function moveActiveOption(direction: 1 | -1) {
    const selectable = options
      .map((brand, index) => (brand.brand_code?.trim() ? index : -1))
      .filter((index) => index >= 0);
    if (!selectable.length) {
      return;
    }
    const current = selectable.indexOf(activeOption);
    const next = current < 0
      ? direction === 1 ? 0 : selectable.length - 1
      : (current + direction + selectable.length) % selectable.length;
    setActiveOption(selectable[next]);
    document.getElementById(`${listId}-option-${selectable[next]}`)?.scrollIntoView({ block: "nearest" });
  }

  return (
    <div
      className="brand-combobox"
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) {
          setOpen(false);
          setActiveOption(-1);
        }
      }}
    >
      <input
        ref={ref}
        id={inputId}
        type="text"
        role="combobox"
        aria-label="搜索并选择品牌"
        aria-autocomplete="list"
        aria-expanded={open && !disabled}
        aria-controls={listId}
        aria-activedescendant={open && !disabled && activeOption >= 0 ? `${listId}-option-${activeOption}` : undefined}
        value={open && !disabled ? search : selectedBrand ? formatBrandOption(selectedBrand) : ""}
        placeholder={loading ? "品牌加载中..." : "搜索品牌名称、别名或编码"}
        disabled={disabled}
        onFocus={() => {
          setSearch("");
          setOpen(true);
        }}
        onClick={() => {
          if (!open) {
            setSearch("");
            setOpen(true);
          }
        }}
        onChange={(event) => {
          setOpen(true);
          setSearch(event.target.value);
          setOptions(event.target.value.trim() ? [] : brands);
          setSearchLoading(Boolean(event.target.value.trim()));
          setSearchError("");
          setActiveOption(-1);
        }}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown" || event.key === "ArrowUp") {
            event.preventDefault();
            if (!open) {
              setSearch("");
              setOpen(true);
            } else {
              moveActiveOption(event.key === "ArrowDown" ? 1 : -1);
            }
          } else if (event.key === "Enter" && open && activeOption >= 0) {
            event.preventDefault();
            const brand = options[activeOption];
            if (brand?.brand_code?.trim()) {
              selectBrand(brand);
            }
          } else if (event.key === "Escape") {
            setOpen(false);
            setActiveOption(-1);
          }
        }}
      />
      {open && !disabled ? (
        <div className="brand-options" id={listId} role="listbox" aria-label="品牌搜索结果">
          {selectedBrand ? (
            <button
              type="button"
              role="option"
              aria-selected={false}
              className="brand-option brand-option-clear"
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => selectBrand(null)}
            >
              清除当前选择
            </button>
          ) : null}
          {searchLoading ? <div className="brand-option-message">搜索中...</div> : null}
          {searchError ? <div className="brand-option-message warning-text">{searchError}</div> : null}
          {!searchLoading && !searchError && !options.length ? (
            <div className="brand-option-message">没有找到匹配的品牌</div>
          ) : null}
          {!searchLoading && !searchError ? options.map((brand, index) => (
            <button
              key={brand.id}
              id={`${listId}-option-${index}`}
              type="button"
              role="option"
              aria-selected={brand.id === selectedBrand?.id}
              tabIndex={-1}
              className={`brand-option ${index === activeOption ? "brand-option-active" : ""}`}
              disabled={!brand.brand_code?.trim()}
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => selectBrand(brand)}
            >
              <span>{formatBrandOption(brand)}</span>
              {brand.brand_alias ? <small>{brand.brand_alias}</small> : null}
            </button>
          )) : null}
        </div>
      ) : null}
    </div>
  );
});

export default BrandSearchSelect;
