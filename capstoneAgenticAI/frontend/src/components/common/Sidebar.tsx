"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { CheckSquare, History, Home, Settings, UploadCloud } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

interface NavItem {
  href: string;
  label: string;
  icon: typeof Home;
  comingSoon?: boolean;
}

const NAV_ITEMS: NavItem[] = [
  { href: "/", label: "Home", icon: Home },
  { href: "/upload", label: "Upload", icon: UploadCloud },
  { href: "/approval", label: "Approvals", icon: CheckSquare },
  { href: "/history", label: "History", icon: History },
  { href: "/settings", label: "Settings", icon: Settings, comingSoon: true },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="hidden w-56 shrink-0 border-r bg-card md:flex md:flex-col print:hidden">
      <nav aria-label="Primary" className="flex flex-1 flex-col gap-1 p-4">
        {NAV_ITEMS.map((item) => {
          const isActive = pathname === item.href;
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              aria-current={isActive ? "page" : undefined}
              className={cn(
                "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                isActive
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:bg-accent hover:text-accent-foreground"
              )}
            >
              <Icon className="h-4 w-4" aria-hidden="true" />
              <span className="flex-1">{item.label}</span>
              {item.comingSoon && (
                <Badge variant="secondary" className="text-[10px]">
                  Soon
                </Badge>
              )}
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}

export { NAV_ITEMS };
