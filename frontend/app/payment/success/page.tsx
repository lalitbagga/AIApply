"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { getCareerGoals } from "@/lib/api";

export default function PaymentSuccessPage() {
  const [creditsBalance, setCreditsBalance] = useState<number | null>(null);

  useEffect(() => {
    // Wait 2s for Stripe webhook to process, then show updated balance
    const timer = setTimeout(() => {
      getCareerGoals()
        .then((data) => setCreditsBalance(data.creditsBalance ?? null))
        .catch(() => {});
    }, 2000);
    return () => clearTimeout(timer);
  }, []);

  return (
    <div className="min-h-screen bg-background flex items-center justify-center p-6">
      <Card className="max-w-md w-full shadow-sm">
        <CardHeader>
          <CardTitle className="text-xl text-center">Payment successful</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4 text-center">
          <p className="text-4xl">✓</p>
          <p className="text-muted-foreground text-[13px]">
            3 CV tailoring credits have been added to your account.
          </p>
          {creditsBalance !== null && (
            <p className="text-[13px] font-medium">
              Your balance: {creditsBalance} credit{creditsBalance === 1 ? "" : "s"}
            </p>
          )}
          <div className="flex gap-3 justify-center pt-2">
            <Button asChild>
              <Link href="/dashboard">Go to Dashboard</Link>
            </Button>
            <Button asChild variant="outline">
              <Link href="/settings">Settings</Link>
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
