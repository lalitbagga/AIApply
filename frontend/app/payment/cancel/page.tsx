"use client";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export default function PaymentCancelPage() {
  return (
    <div className="min-h-screen bg-background flex items-center justify-center p-6">
      <Card className="max-w-md w-full shadow-sm">
        <CardHeader>
          <CardTitle className="text-xl text-center">Payment cancelled</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4 text-center">
          <p className="text-4xl">×</p>
          <p className="text-muted-foreground text-[13px]">
            No charge was made. You can purchase credits any time from Settings.
          </p>
          <div className="flex gap-3 justify-center pt-2">
            <Button asChild variant="outline">
              <Link href="/settings">Back to Settings</Link>
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
