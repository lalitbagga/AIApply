import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

export default function LandingPage() {
  return (
    <div className="min-h-screen bg-background">
      {/* Navigation */}
      <nav className="border-b">
        <div className="max-w-6xl mx-auto px-4 h-16 flex items-center justify-between">
          <span className="text-xl font-bold">AIApply</span>
          <span className="text-sm text-muted-foreground">Private access</span>
        </div>
      </nav>

      {/* Hero */}
      <section className="max-w-6xl mx-auto px-4 py-24 text-center">
        <Badge variant="secondary" className="mb-4">
          5 free applications — no credit card needed
        </Badge>
        <h1 className="text-5xl font-bold tracking-tight mb-6 max-w-3xl mx-auto">
          Stop applying to 200 jobs.{" "}
          <span className="text-primary">Start applying to the right 20.</span>
        </h1>
        <p className="text-xl text-muted-foreground mb-8 max-w-2xl mx-auto">
          Upload your CV once. Tell us your career goals. We find matching jobs,
          tailor your CV for each company, and apply — so you can focus on
          preparing for interviews.
        </p>
        <div className="flex items-center justify-center gap-4">
          <Button size="lg" variant="outline" asChild>
            <Link href="#how-it-works">See How It Works</Link>
          </Button>
        </div>
      </section>

      {/* How It Works */}
      <section id="how-it-works" className="bg-muted/50 py-20">
        <div className="max-w-6xl mx-auto px-4">
          <h2 className="text-3xl font-bold text-center mb-12">
            How It Works
          </h2>
          <div className="grid md:grid-cols-3 gap-8">
            <StepCard
              step="1"
              title="Upload Your CV"
              description="Drop your PDF or DOCX. Our AI extracts your skills, experience, and achievements in seconds."
            />
            <StepCard
              step="2"
              title="Set Career Goals"
              description="Tell us what roles you want, which industries excite you, your salary range, and any dealbreakers."
            />
            <StepCard
              step="3"
              title="Review & Apply"
              description="We find matching jobs, tailor your CV for each one, and show you the changes. Approve and we apply."
            />
          </div>
        </div>
      </section>

      {/* Differentiators */}
      <section className="py-20">
        <div className="max-w-6xl mx-auto px-4">
          <h2 className="text-3xl font-bold text-center mb-4">
            Quality Over Quantity
          </h2>
          <p className="text-center text-muted-foreground mb-12 max-w-2xl mx-auto">
            Other tools blast 200 generic applications. We send 20 that actually
            match your career goals — each with a CV tailored for that specific
            company.
          </p>
          <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-6">
            <FeatureCard
              title="Career Goal Alignment"
              description="Every job is scored against your career direction. We only apply where it advances your goals."
            />
            <FeatureCard
              title="Full CV Tailoring"
              description="Not just keyword stuffing. We restructure your CV to highlight what matters for each specific role."
            />
            <FeatureCard
              title="Complete Transparency"
              description="See exactly what was submitted. Side-by-side diff view of your original CV vs the tailored version."
            />
            <FeatureCard
              title="Company Research"
              description="Each application includes company culture and values research to make your CV truly relevant."
            />
            <FeatureCard
              title="ATS Optimized"
              description="Every tailored CV is optimized to pass Applicant Tracking Systems so humans actually see it."
            />
            <FeatureCard
              title="Track Everything"
              description="Kanban board to track every application from matching to offer. Know exactly where you stand."
            />
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="bg-primary text-primary-foreground py-16">
        <div className="max-w-3xl mx-auto px-4 text-center">
          <h2 className="text-3xl font-bold mb-4">
            Ready to apply smarter?
          </h2>
          <p className="text-lg opacity-90 mb-8">
            Access is currently invitation-only.
          </p>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t py-8">
        <div className="max-w-6xl mx-auto px-4 flex items-center justify-between text-sm text-muted-foreground">
          <span>AIApply</span>
          <span>Built with care for job seekers</span>
        </div>
      </footer>
    </div>
  );
}

function StepCard({
  step,
  title,
  description,
}: {
  step: string;
  title: string;
  description: string;
}) {
  return (
    <Card>
      <CardContent className="pt-6">
        <div className="w-10 h-10 rounded-full bg-primary text-primary-foreground flex items-center justify-center font-bold mb-4">
          {step}
        </div>
        <h3 className="text-lg font-semibold mb-2">{title}</h3>
        <p className="text-muted-foreground">{description}</p>
      </CardContent>
    </Card>
  );
}

function FeatureCard({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <Card>
      <CardContent className="pt-6">
        <h3 className="font-semibold mb-2">{title}</h3>
        <p className="text-sm text-muted-foreground">{description}</p>
      </CardContent>
    </Card>
  );
}
