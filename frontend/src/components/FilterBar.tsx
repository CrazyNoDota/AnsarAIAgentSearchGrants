"use client";

import { useState, useCallback } from "react";
import { Search, X, Filter } from "lucide-react";

interface FilterBarProps {
  onFilterChange: (filters: { status?: string; search?: string; country?: string; category?: string }) => void;
}

const STATUS_OPTIONS = [
  { value: "", label: "All Status" },
  { value: "pending", label: "⏳ Pending" },
  { value: "approved", label: "✅ Approved" },
  { value: "rejected", label: "❌ Rejected" },
];

export default function FilterBar({ onFilterChange }: FilterBarProps) {
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [country, setCountry] = useState("");
  const [category, setCategory] = useState("");

  const apply = useCallback(
    (updates: { search?: string; status?: string; country?: string; category?: string }) => {
      const merged = {
        search: updates.search ?? search,
        status: updates.status ?? status,
        country: updates.country ?? country,
        category: updates.category ?? category,
      };
      onFilterChange({
        search: merged.search || undefined,
        status: merged.status || undefined,
        country: merged.country || undefined,
        category: merged.category || undefined,
      });
    },
    [search, status, country, category, onFilterChange]
  );

  const handleSearchKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") apply({ search });
  };

  const handleClear = () => {
    setSearch(""); setStatus(""); setCountry(""); setCategory("");
    onFilterChange({});
  };

  const hasFilters = search || status || country || category;

  return (
    <div className="glass-card p-4 mb-6">
      <div className="flex flex-wrap gap-3 items-center">
        {/* Search */}
        <div className="relative flex-1 min-w-48">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2"
            style={{ color: "var(--text-muted)" }} />
          <input
            id="grant-search"
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onKeyDown={handleSearchKeyDown}
            placeholder="Search grants..."
            className="input-field pl-9"
          />
        </div>

        {/* Status */}
        <select
          id="filter-status"
          value={status}
          onChange={(e) => { setStatus(e.target.value); apply({ status: e.target.value }); }}
          className="input-field"
          style={{ width: 160 }}>
          {STATUS_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>{opt.label}</option>
          ))}
        </select>

        {/* Country */}
        <input
          id="filter-country"
          type="text"
          value={country}
          onChange={(e) => setCountry(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && apply({ country })}
          placeholder="Country..."
          className="input-field"
          style={{ width: 140 }}
        />

        {/* Category */}
        <input
          id="filter-category"
          type="text"
          value={category}
          onChange={(e) => setCategory(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && apply({ category })}
          placeholder="Category..."
          className="input-field"
          style={{ width: 140 }}
        />

        {/* Apply button */}
        <button
          id="apply-filters"
          onClick={() => apply({})}
          className="btn-primary flex items-center gap-2">
          <Filter size={15} />
          Apply
        </button>

        {/* Clear */}
        {hasFilters && (
          <button onClick={handleClear}
            className="flex items-center gap-1 text-sm px-3 py-2 rounded-lg transition-colors"
            style={{ color: "var(--text-muted)", border: "1px solid var(--border)" }}>
            <X size={14} />
            Clear
          </button>
        )}
      </div>
    </div>
  );
}
