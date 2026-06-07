"use client";

// Account + scope context. The scope switcher (ALL / region / branch) drives every data fetch.
// No auth — switching is just a client-side context change, as specified.

import { createContext, useContext, useState, type ReactNode } from "react";
import { ALL_SCOPE, type Scope } from "@/lib/types";
import { domainConfig } from "@/lib/domainConfig";

interface AccountCtx {
  scope: Scope;
  setScope: (s: Scope) => void;
  regions: string[];
}

const Ctx = createContext<AccountCtx | null>(null);

export function AccountProvider({ children }: { children: ReactNode }) {
  const [scope, setScope] = useState<Scope>(ALL_SCOPE);
  return (
    <Ctx.Provider value={{ scope, setScope, regions: domainConfig.regions }}>
      {children}
    </Ctx.Provider>
  );
}

export function useAccount(): AccountCtx {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAccount must be used within AccountProvider");
  return v;
}
