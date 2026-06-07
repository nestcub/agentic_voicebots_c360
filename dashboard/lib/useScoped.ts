"use client";

// Tiny hook: run a DataSource fetch whenever the active scope changes. Realtime-ready
// (the DataSource can later expose subscribe); for now it refetches on scope change.

import { useEffect, useState } from "react";
import { getDataSource, type DataSource } from "./dataSource";
import { useAccount } from "@/context/AccountContext";
import type { Scope } from "./types";

export function useScoped<T>(fetcher: (ds: DataSource, scope: Scope) => Promise<T>, initial: T): {
  data: T;
  loading: boolean;
} {
  const { scope } = useAccount();
  const [data, setData] = useState<T>(initial);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    setLoading(true);
    getDataSource()
      .then((ds) => fetcher(ds, scope))
      .then((d) => {
        if (active) {
          setData(d);
          setLoading(false);
        }
      });
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scope]);

  return { data, loading };
}
