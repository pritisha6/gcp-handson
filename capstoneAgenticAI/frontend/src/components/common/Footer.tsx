import { APP_ENVIRONMENT } from "@/lib/constants";

export function Footer() {
  return (
    <footer className="border-t px-4 py-4 text-center text-xs text-muted-foreground md:px-6 print:hidden">
      <p>
        ETL Design Agent &middot; {APP_ENVIRONMENT} &middot; &copy; {new Date().getFullYear()}
      </p>
    </footer>
  );
}
