"use client";
import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useTheme } from "next-themes";
import { Sun, Moon, Monitor, Check, ChevronLeft } from "lucide-react";
import { isAuthenticated, signOut } from "@/lib/auth";
import { getCareerGoals, saveCareerGoals, scanJobs, deleteAccount } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

const WORK_ARRANGEMENTS = ["Remote", "Hybrid", "On-site"];

// Claude pricing ($/million tokens) — Haiku 4.5 & Sonnet 4.5
const HAIKU_INPUT_PER_M   = 0.80;
const HAIKU_OUTPUT_PER_M  = 4.00;
const SONNET_INPUT_PER_M  = 3.00;
const SONNET_OUTPUT_PER_M = 15.00;

interface UsageStats {
  haikuInputTokens:   number;
  haikuOutputTokens:  number;
  haikuCalls:         number;
  sonnetInputTokens:  number;
  sonnetOutputTokens: number;
  sonnetCalls:        number;
}

function calcCost(inputTokens: number, outputTokens: number, inputPerM: number, outputPerM: number) {
  return (inputTokens / 1_000_000) * inputPerM + (outputTokens / 1_000_000) * outputPerM;
}

function fmtUsd(usd: number) {
  if (usd === 0) return "$0.00";
  if (usd < 0.005) return "< $0.01";
  return `$${usd.toFixed(2)}`;
}

function formatRelativeTime(isoString: string): string {
  const diff = Date.now() - new Date(isoString).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} minute${mins === 1 ? "" : "s"} ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs} hour${hrs === 1 ? "" : "s"} ago`;
  const days = Math.floor(hrs / 24);
  return `${days} day${days === 1 ? "" : "s"} ago`;
}

const THEME_OPTIONS = [
  {
    value: "light",
    label: "Light",
    icon: Sun,
    preview: (
      <div className="w-full h-10 rounded-lg overflow-hidden flex">
        <div className="w-1/3 bg-slate-100 h-full" />
        <div className="flex-1 bg-white h-full flex flex-col gap-1 p-1.5">
          <div className="h-1.5 w-3/4 rounded bg-slate-200" />
          <div className="h-1.5 w-1/2 rounded bg-slate-100" />
        </div>
      </div>
    ),
  },
  {
    value: "dark",
    label: "Dark",
    icon: Moon,
    preview: (
      <div className="w-full h-10 rounded-lg overflow-hidden flex">
        <div className="w-1/3 h-full" style={{ background: "oklch(0.16 0.016 265)" }} />
        <div className="flex-1 h-full flex flex-col gap-1 p-1.5" style={{ background: "oklch(0.11 0.014 265)" }}>
          <div className="h-1.5 w-3/4 rounded" style={{ background: "oklch(0.24 0.024 265)" }} />
          <div className="h-1.5 w-1/2 rounded" style={{ background: "oklch(0.22 0.018 265)" }} />
        </div>
      </div>
    ),
  },
  {
    value: "system",
    label: "System",
    icon: Monitor,
    preview: (
      <div className="w-full h-10 rounded-lg overflow-hidden flex">
        <div className="w-1/2 h-full flex flex-col gap-1 p-1.5 bg-white border-r border-slate-100">
          <div className="h-1.5 w-3/4 rounded bg-slate-200" />
          <div className="h-1.5 w-1/2 rounded bg-slate-100" />
        </div>
        <div className="w-1/2 h-full flex flex-col gap-1 p-1.5" style={{ background: "oklch(0.11 0.014 265)" }}>
          <div className="h-1.5 w-3/4 rounded" style={{ background: "oklch(0.24 0.024 265)" }} />
          <div className="h-1.5 w-1/2 rounded" style={{ background: "oklch(0.22 0.018 265)" }} />
        </div>
      </div>
    ),
  },
];

export default function SettingsPage() {
  const router = useRouter();
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  const [targetRoles, setTargetRoles] = useState("");
  const [minSalary, setMinSalary] = useState("");
  const [maxSalary, setMaxSalary] = useState("");
  const [locations, setLocations] = useState("");
  const [arrangement, setArrangement] = useState<string[]>(["Remote"]);
  const [minMatchScore, setMinMatchScore] = useState("70");
  const [minAlignmentScore, setMinAlignmentScore] = useState("70");
  const [jobWindowHours, setJobWindowHours] = useState("72");
  const [autoApply, setAutoApply] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [scanDone, setScanDone] = useState(false);
  const [lastScannedAt, setLastScannedAt] = useState<string | null>(null);
  const [usage, setUsage] = useState<UsageStats | null>(null);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [deleteConfirmText, setDeleteConfirmText] = useState("");
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    setMounted(true);
    isAuthenticated().then((ok) => { if (!ok) router.push("/login"); });
    getCareerGoals().then((data) => {
      const g = data.careerGoals ?? {};
      setTargetRoles((g.targetRoles ?? []).join(", "));
      setMinSalary(g.minSalary ?? "");
      setMaxSalary(g.maxSalary ?? "");
      setLocations((g.locations ?? []).join(", "));
      setArrangement(g.workArrangement ?? ["Remote"]);
      setMinMatchScore(
        g.minMatchScore != null && g.minMatchScore !== ""
          ? String(g.minMatchScore)
          : "70"
      );
      setMinAlignmentScore(
        g.minAlignmentScore != null && g.minAlignmentScore !== ""
          ? String(g.minAlignmentScore)
          : "70"
      );
      setJobWindowHours(
        g.jobWindowHours != null && g.jobWindowHours !== ""
          ? String(g.jobWindowHours)
          : "72"
      );
      setLastScannedAt(data.lastScannedAt ?? null);
      if (data.usage) setUsage(data.usage);
    }).catch(() => {});
  }, [router]);

  async function handleScan() {
    setScanning(true);
    setScanDone(false);
    try {
      await scanJobs();
      setScanDone(true);
      setLastScannedAt(new Date().toISOString());
    } catch (err) {
      alert(err instanceof Error ? err.message : "Scan failed. Please try again.");
    } finally {
      setScanning(false);
    }
  }

  async function handleDeleteAccount() {
    if (deleteConfirmText !== "DELETE") return;
    setDeleting(true);
    try {
      await deleteAccount();
      await signOut();
      router.push("/");
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed to delete account. Please try again.");
      setDeleting(false);
    }
  }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    try {
      await saveCareerGoals({
        targetRoles: targetRoles.split(",").map((r) => r.trim()).filter(Boolean),
        minSalary: minSalary ? Number(minSalary) : null,
        maxSalary: maxSalary ? Number(maxSalary) : null,
        locations: locations.split(",").map((l) => l.trim()).filter(Boolean),
        workArrangement: arrangement,
        minMatchScore: minMatchScore ? Number(minMatchScore) : 70,
        minAlignmentScore: minAlignmentScore ? Number(minAlignmentScore) : 70,
        jobWindowHours: jobWindowHours ? Number(jobWindowHours) : 72,
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="min-h-screen bg-background">

      {/* ── Header ── */}
      <header className="border-b border-border/60 sticky top-0 bg-background/80 backdrop-blur-xl z-10">
        <div className="max-w-3xl mx-auto px-6 h-14 flex items-center gap-3">
          <Link
            href="/dashboard"
            className="flex items-center gap-1.5 text-[13px] text-muted-foreground hover:text-foreground transition-colors"
          >
            <ChevronLeft className="w-4 h-4" />
            Dashboard
          </Link>
          <span className="w-px h-4 bg-border" />
          <span className="text-[13px] font-semibold">Settings</span>
        </div>
      </header>

      <main className="max-w-3xl mx-auto px-6 py-8 space-y-5">

        {/* ── Appearance ── */}
        <Card className="shadow-sm border-border/60">
          <CardHeader className="pb-4">
            <CardTitle className="text-base">Appearance</CardTitle>
            <CardDescription>Choose your preferred colour scheme</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-3 gap-3">
              {THEME_OPTIONS.map((opt) => {
                const isActive = mounted && theme === opt.value;
                const Icon = opt.icon;
                return (
                  <button
                    key={opt.value}
                    onClick={() => setTheme(opt.value)}
                    className={`relative rounded-xl p-3 flex flex-col gap-2.5 border-2 transition-all text-left ${
                      isActive
                        ? "border-primary bg-primary/5 shadow-sm"
                        : "border-border/60 hover:border-primary/40 bg-card"
                    }`}
                  >
                    {isActive && (
                      <div className="absolute top-2.5 right-2.5 w-4 h-4 rounded-full bg-primary flex items-center justify-center">
                        <Check className="w-2.5 h-2.5 text-primary-foreground" strokeWidth={3} />
                      </div>
                    )}
                    {opt.preview}
                    <div className="flex items-center gap-1.5 pr-5">
                      <Icon className="w-3.5 h-3.5 text-muted-foreground" />
                      <span className="text-[13px] font-medium">{opt.label}</span>
                    </div>
                  </button>
                );
              })}
            </div>
          </CardContent>
        </Card>

        {/* ── Career Goals ── */}
        <Card className="shadow-sm border-border/60">
          <CardHeader className="pb-4">
            <CardTitle className="text-base">Career Goals</CardTitle>
            <CardDescription>Affects all future job matching and scoring</CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleSave} className="space-y-5">
              <div className="space-y-1.5">
                <Label className="text-[13px]">Target Job Titles</Label>
                <Input
                  placeholder="Senior Software Engineer, Tech Lead"
                  value={targetRoles}
                  onChange={(e) => setTargetRoles(e.target.value)}
                  className="border-border/60"
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <Label className="text-[13px]">Min Salary</Label>
                  <Input type="number" placeholder="60000" value={minSalary} onChange={(e) => setMinSalary(e.target.value)} className="border-border/60" />
                </div>
                <div className="space-y-1.5">
                  <Label className="text-[13px]">Max Salary</Label>
                  <Input type="number" placeholder="120000" value={maxSalary} onChange={(e) => setMaxSalary(e.target.value)} className="border-border/60" />
                </div>
              </div>
              <div className="space-y-1.5">
                <Label className="text-[13px]">Preferred Locations</Label>
                <Input placeholder="London, Remote UK" value={locations} onChange={(e) => setLocations(e.target.value)} className="border-border/60" />
              </div>
              <div className="space-y-2">
                <Label className="text-[13px]">Work Arrangement</Label>
                <div className="flex gap-2 flex-wrap">
                  {WORK_ARRANGEMENTS.map((wa) => (
                    <Badge
                      key={wa}
                      variant={arrangement.includes(wa) ? "default" : "outline"}
                      className="cursor-pointer px-3 py-1 text-xs"
                      onClick={() => setArrangement((p) => p.includes(wa) ? p.filter((a) => a !== wa) : [...p, wa])}
                    >
                      {wa}
                    </Badge>
                  ))}
                </div>
              </div>

              {/* Matching strictness */}
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                <div className="space-y-1.5">
                  <Label className="text-[13px]">
                    Minimum match score
                    <span className="ml-1 text-[11px] text-muted-foreground">(skills fit, 0–100)</span>
                  </Label>
                  <Input
                    type="number"
                    min={0}
                    max={100}
                    value={minMatchScore}
                    onChange={(e) => setMinMatchScore(e.target.value)}
                    className="border-border/60"
                  />
                </div>
                <div className="space-y-1.5">
                  <Label className="text-[13px]">
                    Minimum career alignment
                    <span className="ml-1 text-[11px] text-muted-foreground">(long‑term fit, 0–100)</span>
                  </Label>
                  <Input
                    type="number"
                    min={0}
                    max={100}
                    value={minAlignmentScore}
                    onChange={(e) => setMinAlignmentScore(e.target.value)}
                    className="border-border/60"
                  />
                </div>
                <div className="space-y-1.5">
                  <Label className="text-[13px]">
                    Job age window
                    <span className="ml-1 text-[11px] text-muted-foreground">(hours, 24–336)</span>
                  </Label>
                  <Input
                    type="number"
                    min={24}
                    max={336}
                    value={jobWindowHours}
                    onChange={(e) => setJobWindowHours(e.target.value)}
                    className="border-border/60"
                  />
                </div>
              </div>
              <Button type="submit" disabled={saving} className="h-9 text-[13px]">
                {saved ? "✓ Saved!" : saving ? "Saving…" : "Save Changes"}
              </Button>
            </form>
          </CardContent>
        </Card>

        {/* ── Job Scout ── */}
        <Card className="shadow-sm border-border/60">
          <CardHeader className="pb-4">
            <CardTitle className="text-base">Job Scout</CardTitle>
            <CardDescription>Scan LinkedIn &amp; Indeed for new jobs matching your goals</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center justify-between gap-4">
              <div className="text-[13px] text-muted-foreground">
                {lastScannedAt
                  ? <><span className="text-foreground font-medium">Last scanned</span> {formatRelativeTime(lastScannedAt)}</>
                  : "Never scanned — run a scan after saving career goals"}
              </div>
              <Button onClick={handleScan} disabled={scanning} variant="outline" className="shrink-0 h-9 text-[13px] border-border/60">
                {scanning ? (
                  <span className="flex items-center gap-2">
                    <span className="w-3 h-3 rounded-full border-2 border-primary border-t-transparent animate-spin" />
                    Scanning…
                  </span>
                ) : "🔍 Scan Now"}
              </Button>
            </div>
            {scanDone && (
              <div className="text-[13px] text-emerald-700 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-950/30 border border-emerald-200 dark:border-emerald-800/40 rounded-xl px-3.5 py-2.5 flex items-center gap-2">
                <span>✓</span>
                <span>Scan started — new matches appear in your dashboard in ~2 minutes.</span>
              </div>
            )}
            <p className="text-xs text-muted-foreground">
              ~$0.07 per scan · Haiku model scores 30 jobs · Run daily for fresh results
            </p>
          </CardContent>
        </Card>

        {/* ── Usage & Costs ── */}
        <Card className="shadow-sm border-border/60">
          <CardHeader className="pb-4">
            <CardTitle className="text-base">Usage &amp; Costs</CardTitle>
            <CardDescription>Claude API spend since account creation</CardDescription>
          </CardHeader>
          <CardContent>
            {usage ? (() => {
              const haikuCost  = calcCost(usage.haikuInputTokens,  usage.haikuOutputTokens,  HAIKU_INPUT_PER_M,  HAIKU_OUTPUT_PER_M);
              const sonnetCost = calcCost(usage.sonnetInputTokens, usage.sonnetOutputTokens, SONNET_INPUT_PER_M, SONNET_OUTPUT_PER_M);
              const totalCost  = haikuCost + sonnetCost;
              const rows = [
                {
                  label: "Job Scanning",
                  model: "Haiku 4.5",
                  calls: usage.haikuCalls,
                  callLabel: "scan",
                  cost: haikuCost,
                  colour: "bg-amber-500/10 text-amber-700 dark:text-amber-400",
                },
                {
                  label: "CV Tailoring",
                  model: "Sonnet 4.5",
                  calls: usage.sonnetCalls,
                  callLabel: "CV",
                  cost: sonnetCost,
                  colour: "bg-violet-500/10 text-violet-700 dark:text-violet-400",
                },
              ];
              return (
                <div className="space-y-3">
                  {rows.map((r) => (
                    <div key={r.label} className="flex items-center justify-between gap-4 rounded-xl border border-border/60 px-4 py-3">
                      <div className="min-w-0">
                        <p className="text-[13px] font-medium">{r.label}</p>
                        <p className="text-[11px] text-muted-foreground mt-0.5">
                          {r.calls} {r.callLabel}{r.calls !== 1 ? "s" : ""} · {r.model}
                        </p>
                      </div>
                      <span className={`text-[13px] font-semibold tabular-nums px-2.5 py-1 rounded-lg ${r.colour}`}>
                        {fmtUsd(r.cost)}
                      </span>
                    </div>
                  ))}

                  {/* Total */}
                  <div className="flex items-center justify-between gap-4 rounded-xl bg-primary/5 border border-primary/20 px-4 py-3">
                    <p className="text-[13px] font-semibold">Total</p>
                    <span className="text-[15px] font-bold tabular-nums text-primary">
                      {fmtUsd(totalCost)}
                    </span>
                  </div>

                  <p className="text-[11px] text-muted-foreground pt-1">
                    Haiku: $0.80/$4.00 per M tokens · Sonnet: $3.00/$15.00 per M tokens (input/output)
                  </p>
                </div>
              );
            })() : (
              <p className="text-[13px] text-muted-foreground">No usage recorded yet.</p>
            )}
          </CardContent>
        </Card>

        {/* ── Application Mode ── */}
        <Card className="shadow-sm border-border/60">
          <CardHeader className="pb-4">
            <CardTitle className="text-base">Application Mode</CardTitle>
            <CardDescription>How applications are submitted after tailoring</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {[
              {
                id: "review",
                label: "Review First",
                desc: "You approve each tailored CV before it's submitted",
                recommended: true,
                checked: !autoApply,
                onChange: () => setAutoApply(false),
              },
              {
                id: "auto",
                label: "Auto Apply",
                desc: "Applications submit automatically. You can review afterwards.",
                recommended: false,
                checked: autoApply,
                onChange: () => setAutoApply(true),
              },
            ].map((opt) => (
              <label
                key={opt.id}
                className={`flex items-start gap-3 cursor-pointer rounded-xl border p-4 transition-colors ${
                  opt.checked
                    ? "border-primary/40 bg-primary/5"
                    : "border-border/60 hover:border-primary/20 bg-card"
                }`}
              >
                <input
                  type="radio"
                  name="mode"
                  checked={opt.checked}
                  onChange={opt.onChange}
                  className="mt-0.5 accent-primary"
                />
                <div>
                  <div className="flex items-center gap-2">
                    <p className="text-[13px] font-medium">{opt.label}</p>
                    {opt.recommended && (
                      <span className="text-[10px] font-medium text-primary bg-primary/10 px-2 py-0.5 rounded-full">
                        Recommended
                      </span>
                    )}
                  </div>
                  <p className="text-[12px] text-muted-foreground mt-0.5">{opt.desc}</p>
                </div>
              </label>
            ))}
          </CardContent>
        </Card>

        {/* ── Danger Zone ── */}
        <Card className="shadow-sm border-destructive/30">
          <CardHeader className="pb-4">
            <CardTitle className="text-base text-destructive">Danger Zone</CardTitle>
            <CardDescription>Permanently delete your account and all associated data</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <p className="text-[13px] text-muted-foreground">
              This will delete your profile, all CVs, all applications, and all tailored CV files from storage.
              <span className="font-medium text-foreground"> This cannot be undone.</span>
            </p>

            {!showDeleteConfirm ? (
              <Button
                variant="outline"
                className="border-destructive/40 text-destructive hover:bg-destructive/5 hover:border-destructive h-9 text-[13px]"
                onClick={() => setShowDeleteConfirm(true)}
              >
                Delete My Account
              </Button>
            ) : (
              <div className="space-y-3 rounded-xl border border-destructive/30 bg-destructive/5 p-4">
                <p className="text-[13px] font-medium text-destructive">
                  Type <span className="font-mono font-bold">DELETE</span> to confirm
                </p>
                <div className="flex gap-2">
                  <Input
                    value={deleteConfirmText}
                    onChange={(e) => setDeleteConfirmText(e.target.value)}
                    placeholder="DELETE"
                    className="border-destructive/40 font-mono text-[13px] h-9 w-36"
                    disabled={deleting}
                    autoFocus
                  />
                  <Button
                    onClick={handleDeleteAccount}
                    disabled={deleteConfirmText !== "DELETE" || deleting}
                    className="h-9 text-[13px] bg-destructive hover:bg-destructive/90 text-destructive-foreground"
                  >
                    {deleting ? (
                      <span className="flex items-center gap-2">
                        <span className="w-3 h-3 rounded-full border-2 border-white border-t-transparent animate-spin" />
                        Deleting…
                      </span>
                    ) : "Confirm Delete"}
                  </Button>
                  <Button
                    variant="outline"
                    onClick={() => { setShowDeleteConfirm(false); setDeleteConfirmText(""); }}
                    disabled={deleting}
                    className="h-9 text-[13px] border-border/60"
                  >
                    Cancel
                  </Button>
                </div>
              </div>
            )}
          </CardContent>
        </Card>

      </main>
    </div>
  );
}
