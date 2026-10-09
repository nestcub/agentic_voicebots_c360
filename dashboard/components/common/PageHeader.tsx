import Link from "next/link";
import type { LucideIcon } from "lucide-react";
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb";

export interface Crumb {
  label: string;
  href?: string;
}

// Title row used at the top of every page: optional breadcrumb, an icon tile,
// title + badges, a description, and actions on the right.
export function PageHeader({
  title,
  description,
  icon: Icon,
  iconColor,
  breadcrumbs,
  badges,
  actions,
}: {
  title: string;
  description?: React.ReactNode;
  icon?: LucideIcon;
  /** Tints the icon tile (e.g. a channel's colour); defaults to primary. */
  iconColor?: string;
  breadcrumbs?: Crumb[];
  badges?: React.ReactNode;
  actions?: React.ReactNode;
}) {
  return (
    <div className="space-y-3">
      {breadcrumbs && breadcrumbs.length > 0 && (
        <Breadcrumb>
          <BreadcrumbList>
            {breadcrumbs.map((c, i) => (
              <span key={`${c.label}-${i}`} className="contents">
                {i > 0 && <BreadcrumbSeparator />}
                <BreadcrumbItem>
                  {c.href ? (
                    <BreadcrumbLink asChild>
                      <Link href={c.href}>{c.label}</Link>
                    </BreadcrumbLink>
                  ) : (
                    <BreadcrumbPage>{c.label}</BreadcrumbPage>
                  )}
                </BreadcrumbItem>
              </span>
            ))}
          </BreadcrumbList>
        </Breadcrumb>
      )}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex items-start gap-3 min-w-0">
          {Icon && (
            <div
              className="w-11 h-11 shrink-0 rounded-xl flex items-center justify-center bg-accent text-primary"
              style={iconColor ? { backgroundColor: `${iconColor}1f`, color: iconColor } : undefined}
            >
              <Icon className="w-5 h-5" />
            </div>
          )}
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-xl font-semibold text-foreground">{title}</h1>
              {badges}
            </div>
            {description && <p className="text-sm text-muted-foreground mt-0.5 max-w-2xl">{description}</p>}
          </div>
        </div>
        {actions && <div className="flex flex-wrap items-center gap-2 shrink-0">{actions}</div>}
      </div>
    </div>
  );
}
