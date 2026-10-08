import { useCallback, useMemo } from "react";
import { useSearchParams } from "react-router-dom";

/** Every filter lives in the URL, so any view can be bookmarked or shared. */
export function useFilters() {
  const [sp, setSp] = useSearchParams();

  const filters = useMemo(() => {
    const run = Number(sp.get("run")) || undefined;
    const chains = (sp.get("chains") ?? "").split(",").filter(Boolean);
    return {
      run,
      chains: chains.length ? chains : undefined,
      get: (key: string) => sp.get(key) ?? undefined,
    };
  }, [sp]);

  const set = useCallback(
    (patch: Record<string, string | number | string[] | undefined | null>, resetPage = true) => {
      setSp((prev) => {
        const next = new URLSearchParams(prev);
        for (const [k, v] of Object.entries(patch)) {
          const value = Array.isArray(v) ? v.join(",") : v == null ? "" : String(v);
          if (value) next.set(k, value);
          else next.delete(k);
        }
        if (resetPage && !("page" in patch)) next.delete("page");
        return next;
      });
    },
    [setSp],
  );

  return { ...filters, set };
}
