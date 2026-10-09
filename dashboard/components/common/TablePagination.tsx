"use client";

import { useEffect, useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export const PAGE_SIZE_OPTIONS = [10, 25, 50, 100];

/** Client-side pagination over an already-loaded array. */
export function usePagination<T>(items: T[], initialPageSize = 10) {
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(initialPageSize);

  const pageCount = Math.max(1, Math.ceil(items.length / pageSize));

  // Clamp when the data shrinks (filters, refetch) or the page size grows.
  useEffect(() => {
    if (page > pageCount) setPage(pageCount);
  }, [page, pageCount]);

  const current = Math.min(page, pageCount);
  const start = (current - 1) * pageSize;
  const pageItems = items.slice(start, start + pageSize);

  return {
    page: current,
    setPage,
    pageSize,
    setPageSize: (size: number) => {
      setPageSize(size);
      setPage(1);
    },
    pageCount,
    pageItems,
    total: items.length,
    start,
  };
}

export function TablePagination({
  page,
  pageCount,
  pageSize,
  total,
  start,
  onPageChange,
  onPageSizeChange,
  className,
}: {
  page: number;
  pageCount: number;
  pageSize: number;
  total: number;
  start: number;
  onPageChange: (page: number) => void;
  onPageSizeChange: (size: number) => void;
  className?: string;
}) {
  if (total <= PAGE_SIZE_OPTIONS[0]) return null;

  const from = total === 0 ? 0 : start + 1;
  const to = Math.min(start + pageSize, total);

  return (
    <div
      className={cn(
        "flex flex-wrap items-center justify-between gap-3 border-t border-border px-5 py-3 text-xs text-muted-foreground",
        className,
      )}
    >
      <div className="flex items-center gap-2">
        <span>Rows per page</span>
        <select
          value={pageSize}
          onChange={(e) => onPageSizeChange(Number(e.target.value))}
          className="rounded-md border border-border bg-background px-1.5 py-1 text-xs text-foreground"
          aria-label="Rows per page"
        >
          {PAGE_SIZE_OPTIONS.map((n) => (
            <option key={n} value={n}>
              {n}
            </option>
          ))}
        </select>
      </div>
      <div className="flex items-center gap-3">
        <span className="tabular-nums">
          {from}–{to} of {total}
        </span>
        <div className="flex items-center gap-1">
          <Button
            variant="outline"
            size="icon-sm"
            onClick={() => onPageChange(page - 1)}
            disabled={page <= 1}
            aria-label="Previous page"
          >
            <ChevronLeft />
          </Button>
          <span className="px-1 tabular-nums">
            {page} / {pageCount}
          </span>
          <Button
            variant="outline"
            size="icon-sm"
            onClick={() => onPageChange(page + 1)}
            disabled={page >= pageCount}
            aria-label="Next page"
          >
            <ChevronRight />
          </Button>
        </div>
      </div>
    </div>
  );
}
