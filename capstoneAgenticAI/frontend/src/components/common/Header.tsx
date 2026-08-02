"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Workflow } from "lucide-react";

import { cn } from "@/lib/utils";
import { NAV_ITEMS } from "@/components/common/Sidebar";

export function Header() {
  const pathname = usePathname();

  return (
    <header className="sticky top-0 z-40 flex h-14 items-center gap-4 border-b bg-background/95 px-4 backdrop-blur supports-[backdrop-filter]:bg-background/60 md:px-6 print:hidden">
      <Link href="/" className="flex items-center gap-2 font-semibold">
        <Workflow className="h-5 w-5 text-primary" aria-hidden="true" />
        <span>ETL Design Agent</span>
      </Link>

      {/* Mobile nav: horizontal scroll row shown below md, where the Sidebar is hidden */}
      <nav aria-label="Primary" className="flex flex-1 items-center gap-1 overflow-x-auto md:hidden">
        {NAV_ITEMS.map((item) => {
          const isActive = pathname === item.href;
          return (
            <Link
              key={item.href}
              href={item.href}
              aria-current={isActive ? "page" : undefined}
              className={cn(
                "whitespace-nowrap rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
                isActive
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:bg-accent hover:text-accent-foreground"
              )}
            >
              {item.label}
            </Link>
          );
        })}
      </nav>
    </header>
  );
}
