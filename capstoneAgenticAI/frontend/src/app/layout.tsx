import type { Metadata, Viewport } from "next";

import "@/styles/globals.css";
import { Footer } from "@/components/common/Footer";
import { Header } from "@/components/common/Header";
import { Sidebar } from "@/components/common/Sidebar";
import { TooltipProvider } from "@/components/ui/tooltip";

export const metadata: Metadata = {
  title: {
    default: "ETL Design Agent",
    template: "%s | ETL Design Agent",
  },
  description:
    "AI system that generates optimal Google Cloud Platform ETL architecture designs in 15-20 minutes.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className="min-h-screen antialiased">
        <TooltipProvider delayDuration={200}>
          <div className="flex min-h-screen flex-col">
            <Header />
            <div className="flex flex-1">
              <Sidebar />
              <main className="flex-1 px-4 py-6 md:px-8 md:py-8 print:p-0">{children}</main>
            </div>
            <Footer />
          </div>
        </TooltipProvider>
      </body>
    </html>
  );
}
