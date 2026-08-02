import Link from "next/link";
import { ArrowRight, FileSearch, History, Settings, Sparkles, UploadCloud } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

const QUICK_LINKS = [
  {
    href: "/upload",
    title: "Upload Requirements",
    description: "Upload documents or fill out a form to describe your ETL pipeline needs.",
    icon: UploadCloud,
  },
  {
    href: "/history",
    title: "Design History",
    description: "Browse previously generated designs and their approval status.",
    icon: History,
    comingSoon: true,
  },
  {
    href: "/settings",
    title: "Settings",
    description: "Manage integrations, defaults, and account preferences.",
    icon: Settings,
    comingSoon: true,
  },
];

const HOW_IT_WORKS = [
  {
    step: "1",
    title: "Describe your requirements",
    description:
      "Upload source documents (PDF, PPTX, XLSX, HTML, TXT, CSV) and/or fill out a structured form covering data sources, performance, budget, team, and compliance needs.",
    icon: FileSearch,
  },
  {
    step: "2",
    title: "AI-driven design generation",
    description:
      "Claude, combined with RAG over prior designs and a Tree-of-Thought search, evaluates GCP architecture options against your constraints.",
    icon: Sparkles,
  },
  {
    step: "3",
    title: "Review a complete design package",
    description:
      "In 15-20 minutes, receive an architecture diagram, decision matrix, cost analysis, compliance checklist, and implementation roadmap, ready for stakeholder approval.",
    icon: ArrowRight,
  },
];

export default function HomePage() {
  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-10">
      <section className="flex flex-col gap-3">
        <h1 className="text-3xl font-bold tracking-tight md:text-4xl">
          Welcome to the ETL Design Agent
        </h1>
        <p className="max-w-2xl text-muted-foreground">
          Describe your data pipeline requirements and get an optimal Google Cloud Platform ETL
          architecture design, complete with cost analysis and a compliance checklist, in 15-20
          minutes.
        </p>
        <div>
          <Button asChild size="lg">
            <Link href="/upload">
              Start a new design
              <ArrowRight className="h-4 w-4" aria-hidden="true" />
            </Link>
          </Button>
        </div>
      </section>

      <section aria-labelledby="quick-links-heading" className="flex flex-col gap-4">
        <h2 id="quick-links-heading" className="text-xl font-semibold tracking-tight">
          Quick links
        </h2>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {QUICK_LINKS.map((link) => {
            const Icon = link.icon;
            return (
              <Link key={link.href} href={link.href} className="group">
                <Card className="h-full transition-colors group-hover:border-primary">
                  <CardHeader>
                    <div className="flex items-center justify-between">
                      <Icon className="h-6 w-6 text-primary" aria-hidden="true" />
                      {link.comingSoon && <Badge variant="secondary">Coming soon</Badge>}
                    </div>
                    <CardTitle className="mt-2">{link.title}</CardTitle>
                    <CardDescription>{link.description}</CardDescription>
                  </CardHeader>
                </Card>
              </Link>
            );
          })}
        </div>
      </section>

      <section aria-labelledby="how-it-works-heading" className="flex flex-col gap-4">
        <h2 id="how-it-works-heading" className="text-xl font-semibold tracking-tight">
          How it works
        </h2>
        <div className="grid gap-4 md:grid-cols-3">
          {HOW_IT_WORKS.map((item) => {
            const Icon = item.icon;
            return (
              <Card key={item.step}>
                <CardHeader>
                  <div className="flex items-center gap-2">
                    <span className="flex h-8 w-8 items-center justify-center rounded-full bg-primary text-sm font-semibold text-primary-foreground">
                      {item.step}
                    </span>
                    <Icon className="h-5 w-5 text-muted-foreground" aria-hidden="true" />
                  </div>
                  <CardTitle className="mt-2 text-base">{item.title}</CardTitle>
                  <CardDescription>{item.description}</CardDescription>
                </CardHeader>
              </Card>
            );
          })}
        </div>
      </section>
    </div>
  );
}
