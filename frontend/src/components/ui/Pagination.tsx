import { cn } from "@/lib/utils";

interface PaginationProps {
  page: number;
  pages: number;
  total?: number;
  limit?: number;
  onChange: (page: number) => void;
  className?: string;
}

export function Pagination({ page, pages, total, limit, onChange, className }: PaginationProps) {
  if (pages <= 1) return null;

  const getPageList = (): (number | "...")[] => {
    if (pages <= 7) {
      return Array.from({ length: pages }, (_, i) => i + 1);
    }
    const result: (number | "...")[] = [1];
    if (page > 3) result.push("...");
    const start = Math.max(2, page - 1);
    const end = Math.min(pages - 1, page + 1);
    for (let i = start; i <= end; i++) result.push(i);
    if (page < pages - 2) result.push("...");
    result.push(pages);
    return result;
  };

  const from = total && limit ? Math.min((page - 1) * limit + 1, total) : null;
  const to = total && limit ? Math.min(page * limit, total) : null;

  return (
    <div className={cn("flex flex-col sm:flex-row items-center justify-between gap-3", className)}>
      {total != null && from != null && to != null && (
        <p className="text-sm text-gray-500">
          Showing <span className="text-gray-300 font-medium">{from}–{to}</span> of{" "}
          <span className="text-gray-300 font-medium">{total}</span>
        </p>
      )}
      <div className="flex items-center gap-1 ml-auto">
        <button
          disabled={page <= 1}
          onClick={() => onChange(page - 1)}
          className="px-3 py-1.5 text-sm rounded-xl disabled:opacity-30 disabled:cursor-not-allowed hover:bg-white/10 text-gray-400 hover:text-white transition-colors"
          aria-label="Previous page"
        >
          ‹ Prev
        </button>

        {getPageList().map((p, i) =>
          p === "..." ? (
            <span key={`ellipsis-${i}`} className="w-9 text-center text-gray-500 select-none">
              …
            </span>
          ) : (
            <button
              key={p}
              onClick={() => onChange(p as number)}
              aria-current={p === page ? "page" : undefined}
              className={cn(
                "w-9 h-9 text-sm rounded-xl font-medium transition-colors",
                p === page
                  ? "bg-brand-600 text-white shadow-lg shadow-brand-600/30"
                  : "hover:bg-white/10 text-gray-400 hover:text-white"
              )}
            >
              {p}
            </button>
          )
        )}

        <button
          disabled={page >= pages}
          onClick={() => onChange(page + 1)}
          className="px-3 py-1.5 text-sm rounded-xl disabled:opacity-30 disabled:cursor-not-allowed hover:bg-white/10 text-gray-400 hover:text-white transition-colors"
          aria-label="Next page"
        >
          Next ›
        </button>
      </div>
    </div>
  );
}

export default Pagination;
