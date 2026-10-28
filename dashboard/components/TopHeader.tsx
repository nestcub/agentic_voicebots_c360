"use client";

import { useEffect, useState } from "react";
import { Building2, Calendar, ChevronDown, LogOut, ShieldCheck } from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { fetchMe, getOrganization, logout, setOrganization, type Me } from "@/lib/auth";
import { displayName, domainConfig } from "@/lib/domainConfig";
import { useSidebar } from "@/context/SidebarContext";

function UserMenu({ me, org }: { me: Me; org: string | null }) {
  const current = me.organizations.find((o) => o.slug === org) ?? me.organizations[0];
  const username = displayName(me.username);

  function switchOrg(slug: string) {
    if (slug === org) return;
    setOrganization(slug);
    window.location.reload(); // every page's data is org-scoped
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          className="flex items-center gap-2 rounded-full pl-3 pr-2 py-1 hover:bg-accent transition-colors outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
          aria-label="Account menu"
        >
          <span className="flex flex-col items-start leading-tight text-left">
            <span className="text-sm font-medium text-foreground max-w-36 truncate">{username}</span>
            {current && <span className="text-xs text-muted-foreground max-w-36 truncate">{displayName(current.name)}</span>}
          </span>
          <ChevronDown className="w-4 h-4 text-muted-foreground" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-64">
        <DropdownMenuLabel className="font-normal">
          <p className="text-sm font-medium text-foreground truncate">{username}</p>
          <p className="text-xs text-muted-foreground truncate">
            {current ? `${current.role} · ${displayName(current.name)}` : "No organization"}
          </p>
          {me.is_platform_staff && (
            <p className="mt-1 inline-flex items-center gap-1 text-xs text-primary">
              <ShieldCheck className="w-3 h-3" /> Platform staff
            </p>
          )}
        </DropdownMenuLabel>

        {me.organizations.length > 1 && (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuLabel className="text-xs text-muted-foreground">Organization</DropdownMenuLabel>
            <DropdownMenuRadioGroup value={current?.slug} onValueChange={switchOrg}>
              {me.organizations.map((o) => (
                <DropdownMenuRadioItem key={o.slug} value={o.slug}>
                  <Building2 className="text-muted-foreground" />
                  <span className="truncate">{displayName(o.name)}</span>
                </DropdownMenuRadioItem>
              ))}
            </DropdownMenuRadioGroup>
          </>
        )}

        <DropdownMenuSeparator />
        <DropdownMenuItem variant="destructive" onSelect={logout}>
          <LogOut /> Sign out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export function TopHeader() {
  const { isOpen } = useSidebar();

  // Formatted client-side only, so the server-rendered markup never disagrees
  // with the browser's date/locale.
  const [today, setToday] = useState<string | null>(null);
  useEffect(() => {
    setToday(new Date().toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }));
  }, []);

  // Only present once logged in (the backend runs open until TELEHUB_AUTH_REQUIRED is on).
  const [me, setMe] = useState<Me | null>(null);
  const [org, setOrg] = useState<string | null>(null);
  const [logoOk, setLogoOk] = useState(true);
  useEffect(() => {
    fetchMe().then((m) => {
      setMe(m);
      setOrg(getOrganization() ?? m?.organizations[0]?.slug ?? null);
    });
  }, []);

  return (
    <header
      className={`fixed top-0 right-0 h-16 bg-surface border-b border-border flex items-center justify-between px-6 z-10 transition-all duration-300 ${
        isOpen ? "left-56" : "left-16"
      }`}
    >
      {/* Greeting */}
      <div className="flex items-center gap-3 min-w-0">
        {logoOk && (
          // eslint-disable-next-line @next/next/no-img-element -- plain <img> so a missing file can hide itself
          <img
            src={domainConfig.logo}
            alt={domainConfig.brand}
            className="h-9 w-auto shrink-0"
            onError={() => setLogoOk(false)}
          />
        )}
        <p className="min-w-0 text-base font-semibold text-foreground truncate">Hello, {domainConfig.brand}</p>
      </div>

      {/* Right side */}
      <div className="flex items-center gap-4 shrink-0">
        {today && (
          <div className="hidden sm:flex items-center gap-2 text-sm text-foreground">
            <Calendar className="w-4 h-4 text-muted-foreground" />
            <span>{today}</span>
          </div>
        )}
        {me && (
          <>
            <span className="hidden sm:block h-8 w-px bg-border" aria-hidden="true" />
            <UserMenu me={me} org={org} />
          </>
        )}
      </div>
    </header>
  );
}
