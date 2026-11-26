"use client";
import { useEffect, useState } from "react";
import { api } from "./api";
import type { FiltersMeta } from "./types";

let metaCache: FiltersMeta | null = null;

export function useFilterMeta(): FiltersMeta | null {
  const [meta, setMeta] = useState<FiltersMeta | null>(metaCache);
  useEffect(() => {
    if (metaCache) return;
    api
      .filters()
      .then((m) => {
        metaCache = m;
        setMeta(m);
      })
      .catch(() => undefined); // the forms still work with free text
  }, []);
  return meta;
}
