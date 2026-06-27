"use client";

import { useRouter } from "next/navigation";
import { useDemo } from "@/hooks/useDemo";
import { useScrollReveal } from "@/hooks/useScrollReveal";
import { useState, useEffect } from "react";
import {
  Database, ArrowRight, MessageSquare, Code2, Play, Sparkles, Lock,
  Layers, Link2, BarChart3, Lightbulb, Eye, ShieldCheck, Anchor,
  Building2, Menu, X, Search, Clock, Table as TableIcon, Check,
} from "lucide-react";

/* ─── Data ──────────────────────────────────────────── */
const navLinks = [
  { label: "Product", href: "#product" },
  { label: "How it works", href: "#how" },
];

const steps = [
  { icon: MessageSquare, title: "Ask", desc: "Type a question in plain English." },
  { icon: Code2, title: "Generate & preview SQL", desc: "See the query before it runs." },
  { icon: Play, title: "Run (read-only)", desc: "Execute safely against your data." },
  { icon: Sparkles, title: "Insights", desc: "Get charts, context, and next steps." },
];

const capabilities = [
  { icon: MessageSquare, title: "Natural language to SQL", desc: "Translate questions into precise queries automatically." },
  { icon: Lock, title: "Read-only safety", desc: "Queries can never modify or delete your data." },
  { icon: Layers, title: "Semantic metrics layer", desc: "Define revenue, MRR, and churn once. Reuse everywhere." },
  { icon: Link2, title: "Source traceability", desc: "Every number links back to the query that produced it." },
  { icon: BarChart3, title: "Charts & insights", desc: "Auto-generated visuals tuned to your question." },
  { icon: Lightbulb, title: "Business reasoning", desc: "Consultant-level analysis with clear recommendations." },
];

const tourItems = [
  { label: "Ask", icon: MessageSquare, title: "A clean prompt for any question", desc: "Start typing — TallyAI understands schema, joins, and intent." },
  { label: "Results & sources", icon: TableIcon, title: "Answers grounded in your data", desc: "Every row, chart, and number ties back to a verifiable query." },
  { label: "Metrics", icon: Layers, title: "A semantic layer your team agrees on", desc: "Define key business metrics once and let everyone reuse them." },
  { label: "History", icon: Clock, title: "Searchable query history", desc: "Revisit prior questions, share them, and build on past work." },
];

const trust = [
  { icon: Eye, title: "Read-only by default" },
  { icon: ShieldCheck, title: "Preview before run" },
  { icon: Anchor, title: "Grounded answers" },
  { icon: Building2, title: "Multi-tenant isolation" },
];

const footerAnchor: Record<string, string> = {
  Features: "#capabilities",
  "How it works": "#how",
  Product: "#product",
};

/* ─── Helpers ────────────────────────────────────────── */
function RevealSection({ children, className = "", delay = 0 }: { children: React.ReactNode; className?: string; delay?: number }) {
  const { ref, isVisible } = useScrollReveal();
  return (
    <div
      ref={ref}
      className={`transition-all duration-700 ease-out ${isVisible ? "translate-y-0 opacity-100" : "translate-y-8 opacity-0"} ${className}`}
      style={{ transitionDelay: `${delay}ms` }}
    >{children}</div>
  );
}

function Pill({ children }: { children: React.ReactNode }) {
  return <span className="inline-block rounded-full border border-border bg-card px-3 py-1 text-xs font-semibold text-primary">{children}</span>;
}

/* ─── Page ───────────────────────────────────────────── */
export default function LandingPage() {
  const { enterDemoMode } = useDemo();
  const router = useRouter();

  const handleTryDemo = () => {
    enterDemoMode();
    router.push("/workspace/ask");
  };

  const [scrolled, setScrolled] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [tourActive, setTourActive] = useState(0);

  useEffect(() => {
    const handleScroll = () => setScrolled(window.scrollY > 40);
    window.addEventListener("scroll", handleScroll, { passive: true });
    return () => window.removeEventListener("scroll", handleScroll);
  }, []);

  const tourItem = tourItems[tourActive];

  return (
    <div className="min-h-screen bg-background text-foreground">
      {/* Nav */}
      <nav className={`fixed top-0 left-0 right-0 z-50 transition-all duration-300 ${scrolled ? "bg-background/90 border-b border-border backdrop-blur-md" : "bg-transparent"}`}>
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3 sm:px-6">
          <a href="#" className="flex items-center gap-2">
            <span className="inline-flex h-7 w-7 items-center justify-center rounded-md bg-primary text-primary-foreground"><Database className="h-4 w-4" /></span>
            <span className="text-lg font-semibold tracking-tight">TallyAI</span>
          </a>
          <div className="hidden items-center gap-8 md:flex">
            {navLinks.map((l) => (
              <a key={l.label} href={l.href} className="text-sm font-medium text-muted-foreground transition-colors hover:text-foreground">{l.label}</a>
            ))}
          </div>
          <button type="button" onClick={handleTryDemo} className="hidden items-center gap-1.5 rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground shadow-sm transition-all hover:brightness-110 md:inline-flex">
            Try demo <ArrowRight className="h-3.5 w-3.5" />
          </button>
          <button type="button" onClick={() => setMobileOpen(!mobileOpen)} className="md:hidden p-2 text-foreground" aria-label="Toggle menu">
            {mobileOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
          </button>
        </div>
        {mobileOpen && (
          <div className="border-t border-border bg-background px-4 pb-4 md:hidden">
            {navLinks.map((l) => <a key={l.label} href={l.href} onClick={() => setMobileOpen(false)} className="block py-3 text-sm font-medium text-muted-foreground">{l.label}</a>)}
            <button type="button" onClick={() => { setMobileOpen(false); handleTryDemo(); }} className="mt-2 w-full rounded-lg bg-primary px-5 py-2.5 text-sm font-semibold text-primary-foreground">Try demo</button>
          </div>
        )}
      </nav>

      {/* Hero */}
      <section className="relative px-4 pt-28 pb-16 sm:px-6 sm:pt-32 sm:pb-24">
        <div className="mx-auto flex max-w-3xl flex-col items-center text-center">
          <h1 className="text-[34px] font-semibold leading-[1.05] tracking-tight sm:text-[48px] lg:text-[56px]">Ask your database<br />anything.</h1>
          <p className="mt-5 max-w-xl text-base leading-relaxed text-muted-foreground sm:text-lg">Plain-English questions in. Safe, explainable SQL and consultant-level insights out.</p>
          <div className="mt-8">
            <button type="button" onClick={handleTryDemo} className="group inline-flex items-center gap-2 rounded-lg bg-primary px-6 py-3 text-base font-semibold text-primary-foreground shadow-lg transition-all hover:shadow-xl hover:brightness-110">
              Try demo <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-1" />
            </button>
          </div>
          {/* Inline hero visual */}
          <div className="mt-14 w-full max-w-xl mx-auto overflow-hidden rounded-xl border border-border bg-card shadow-xl">
            <div className="flex items-center gap-2 border-b border-border bg-muted/60 px-4 py-2.5"><div className="h-2.5 w-2.5 rounded-full bg-destructive/60" /><div className="h-2.5 w-2.5 rounded-full bg-secondary/60" /><div className="h-2.5 w-2.5 rounded-full bg-stock-healthy/60" /></div>
            <div className="bg-card p-5">
              <div className="flex items-center gap-2 rounded-lg border border-border bg-muted/50 px-3 py-2.5"><Search className="h-4 w-4 text-muted-foreground" /><span className="text-sm text-foreground">What was our top revenue product last quarter?</span></div>
              <div className="mt-4 rounded-lg border border-border bg-foreground/[0.04] p-3 font-mono text-[11px] leading-relaxed text-foreground">
                <div><span className="text-primary">SELECT</span> product_name, <span className="text-primary">SUM</span>(amount) <span className="text-primary">AS</span> revenue</div>
                <div><span className="text-primary">FROM</span> orders</div>
                <div><span className="text-primary">WHERE</span> created_at <span className="text-primary">&gt;=</span> <span className="text-secondary">&apos;2026-01-01&apos;</span></div>
                <div><span className="text-primary">GROUP BY</span> product_name <span className="text-primary">ORDER BY</span> revenue <span className="text-primary">DESC</span> <span className="text-primary">LIMIT</span> 5;</div>
              </div>
              <div className="mt-4 grid grid-cols-5 items-end gap-2 h-24">{[80,60,45,30,22].map((h,i) => <div key={i} className="rounded-t-sm bg-primary/80" style={{ height: `${h}%` }} />)}</div>
              <div className="mt-3 flex items-center justify-between text-xs text-muted-foreground"><span>5 rows · 142 ms</span><span className="inline-flex items-center gap-1 text-primary font-medium"><Sparkles className="h-3 w-3" /> Insight ready</span></div>
            </div>
          </div>
        </div>
      </section>

      {/* How it works */}
      <section id="how" className="bg-muted/50 px-4 py-20 sm:py-28">
        <RevealSection className="text-center"><Pill>How it works</Pill><h2 className="mt-4 text-2xl font-semibold tracking-tight sm:text-3xl">From question to insight in four steps</h2></RevealSection>
        <div className="mx-auto mt-14 grid max-w-6xl grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {steps.map((s, i) => (
            <RevealSection key={s.title} delay={i * 100}>
              <div className="h-full rounded-xl border border-border bg-card p-6">
                <div className="flex items-center justify-between"><div className="inline-flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10 text-primary"><s.icon className="h-5 w-5" /></div><span className="font-mono text-xs text-muted-foreground">0{i + 1}</span></div>
                <h3 className="mt-4 text-sm font-semibold">{s.title}</h3>
                <p className="mt-1 text-sm leading-relaxed text-muted-foreground">{s.desc}</p>
              </div>
            </RevealSection>
          ))}
        </div>
      </section>

      {/* Capabilities */}
      <section id="capabilities" className="px-4 py-20 sm:py-28">
        <RevealSection className="text-center"><Pill>Capabilities</Pill><h2 className="mt-4 text-2xl font-semibold tracking-tight sm:text-3xl lg:text-4xl">Everything you need to query with confidence</h2></RevealSection>
        <div className="mx-auto mt-14 grid max-w-5xl grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {capabilities.map((c, i) => (
            <RevealSection key={c.title} delay={i * 70}>
              <div className="h-full rounded-xl border border-border bg-card p-6 transition-all duration-200 hover:-translate-y-1 hover:shadow-md">
                <div className="inline-flex rounded-lg bg-primary/10 p-2.5 text-primary"><c.icon className="h-5 w-5" /></div>
                <h3 className="mt-4 text-sm font-semibold">{c.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{c.desc}</p>
              </div>
            </RevealSection>
          ))}
        </div>
      </section>

      {/* Product Tour */}
      <section id="product" className="px-4 py-20 sm:py-28">
        <RevealSection className="text-center"><Pill>Product tour</Pill><h2 className="mt-4 text-2xl font-semibold tracking-tight sm:text-3xl lg:text-4xl">See TallyAI from every angle</h2><p className="mx-auto mt-4 max-w-2xl text-base text-muted-foreground">Click through the surfaces your team will use every day.</p></RevealSection>
        <div className="mx-auto mt-14 flex max-w-6xl flex-col gap-8 lg:flex-row lg:gap-12">
          <div className="flex justify-center gap-2 overflow-x-auto lg:w-72 lg:shrink-0 lg:justify-start lg:flex-col lg:gap-2">
            {tourItems.map((t, i) => (
              <button key={t.label} type="button" onClick={() => setTourActive(i)} className={`shrink-0 inline-flex items-center gap-2.5 rounded-lg px-4 py-3 text-left text-sm font-medium transition-all ${tourActive === i ? "bg-card text-foreground shadow-sm ring-1 ring-border" : "bg-transparent text-muted-foreground hover:bg-muted/60 hover:text-foreground"}`}>
                <t.icon className="h-4 w-4" />{t.label}
              </button>
            ))}
          </div>
          <div className="flex-1 overflow-hidden rounded-xl border border-border bg-card shadow-xl">
            <div className="flex items-center gap-2 border-b border-border bg-muted/60 px-4 py-2.5"><div className="h-2.5 w-2.5 rounded-full bg-destructive/60" /><div className="h-2.5 w-2.5 rounded-full bg-secondary/60" /><div className="h-2.5 w-2.5 rounded-full bg-stock-healthy/60" /></div>
            <div className="bg-card p-8 min-h-[280px]">
              <div className="flex items-center gap-2 text-primary"><tourItem.icon className="h-5 w-5" /><span className="text-xs font-semibold uppercase tracking-wide">{tourItem.label}</span></div>
              <h3 className="mt-3 text-xl font-semibold tracking-tight">{tourItem.title}</h3>
              <p className="mt-2 text-sm text-muted-foreground max-w-md">{tourItem.desc}</p>
              <div className="mt-6 grid grid-cols-3 gap-3">{[0,1,2].map((j) => <div key={j} className="rounded-lg border border-border bg-muted/40 p-3"><div className="h-2 w-12 rounded-full bg-muted-foreground/30" /><div className="mt-2 h-3 w-20 rounded-full bg-foreground/70" /><div className="mt-3 h-12 rounded-md bg-primary/15" /></div>)}</div>
            </div>
          </div>
        </div>
      </section>

      {/* Trust */}
      <section className="px-4 py-16">
        <RevealSection>
          <div className="mx-auto grid max-w-5xl grid-cols-2 gap-4 sm:grid-cols-4">
            {trust.map((t) => (
              <div key={t.title} className="flex flex-col items-center gap-3 rounded-xl border border-border bg-card p-5 text-center">
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10"><t.icon className="h-5 w-5 text-primary" /></div>
                <span className="text-sm font-medium text-foreground">{t.title}</span>
              </div>
            ))}
          </div>
        </RevealSection>
      </section>

      {/* Final CTA */}
      <section className="px-4 py-20 sm:py-28">
        <RevealSection>
          <div className="mx-auto max-w-5xl rounded-2xl bg-primary px-6 py-16 text-center text-primary-foreground">
            <div className="mx-auto inline-flex h-12 w-12 items-center justify-center rounded-xl bg-primary-foreground/15"><Database className="h-6 w-6" /></div>
            <h2 className="mt-5 text-2xl font-semibold tracking-tight sm:text-3xl lg:text-4xl">Ready to talk to your data?</h2>
            <p className="mx-auto mt-3 max-w-lg text-base text-primary-foreground/85">Explore TallyAI with sample data. No setup required.</p>
            <button type="button" onClick={handleTryDemo} className="group mt-8 inline-flex items-center gap-2 rounded-lg bg-card px-6 py-3 text-base font-semibold text-foreground shadow-lg transition-all hover:brightness-105">
              Try demo <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-1" />
            </button>
          </div>
        </RevealSection>
      </section>

      {/* Footer */}
      <footer className="border-t border-border px-4 py-12">
        <div className="mx-auto grid max-w-6xl grid-cols-2 gap-8 sm:grid-cols-4">
          <div className="col-span-2 sm:col-span-1">
            <div className="flex items-center gap-2"><span className="inline-flex h-7 w-7 items-center justify-center rounded-md bg-primary text-primary-foreground"><Database className="h-4 w-4" /></span><span className="text-base font-semibold tracking-tight">TallyAI</span></div>
            <p className="mt-3 text-sm text-muted-foreground">Ask your database anything.</p>
          </div>
          {[{ title: "Product", links: ["Features","How it works","Changelog"]},{ title: "Company", links: ["About","Customers","Careers","Contact"]},{ title: "Resources", links: ["Docs","Security","Privacy","Terms"]}].map((col) => (
            <div key={col.title}><h4 className="text-xs font-semibold uppercase tracking-wide text-foreground">{col.title}</h4><ul className="mt-3 space-y-2">{col.links.map((l) => <li key={l}><a href={footerAnchor[l] ?? "#"} className="text-sm text-muted-foreground transition-colors hover:text-foreground">{l}</a></li>)}</ul></div>
          ))}
        </div>
        <div className="mx-auto mt-10 flex max-w-6xl items-center justify-between border-t border-border pt-6 text-xs text-muted-foreground">
          <span>© {new Date().getFullYear()} TallyAI. All rights reserved.</span>
          <span>Built with care.</span>
        </div>
      </footer>
    </div>
  );
}
