import { getAuthToken } from "./auth";

const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:3001").replace(/\/$/, "");

async function apiFetch(path: string, options: RequestInit = {}) {
  const token = await getAuthToken();
  const res = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options.headers,
    },
  });
  if (!res.ok) throw new Error(`API error ${res.status}: ${await res.text()}`);
  return res.json();
}

// --- CV ---
export async function getUploadUrl(fileName: string, fileType: string) {
  return apiFetch("/api/upload-url", {
    method: "POST",
    body: JSON.stringify({ fileName, fileType }),
  });
}

export async function uploadFileToS3(uploadUrl: string, file: File) {
  const res = await fetch(uploadUrl, {
    method: "PUT",
    body: file,
    headers: { "Content-Type": file.type },
  });
  if (!res.ok) throw new Error("S3 upload failed");
}

export async function getProfile() {
  return apiFetch("/api/profile");
}

// --- Career Goals ---
export async function saveCareerGoals(goals: Record<string, unknown>) {
  return apiFetch("/api/career-goals", {
    method: "POST",
    body: JSON.stringify(goals),
  });
}

export async function getCareerGoals() {
  return apiFetch("/api/career-goals");
}

// --- Applications ---
export async function getApplications(limit = 100) {
  return apiFetch(`/api/applications?limit=${limit}`);
}

export async function approveApplication(applicationId: string) {
  return apiFetch("/api/applications/approve", {
    method: "POST",
    body: JSON.stringify({ applicationId }),
  });
}

export async function getTailoredCV(applicationId: string) {
  return apiFetch(`/api/applications/tailored-cv?applicationId=${encodeURIComponent(applicationId)}`);
}

export async function deleteApplication(applicationId: string) {
  return apiFetch(`/api/applications?applicationId=${encodeURIComponent(applicationId)}`, {
    method: "DELETE",
  });
}

export async function tailorApplication(applicationId: string) {
  return apiFetch("/api/applications/tailor", {
    method: "POST",
    body: JSON.stringify({ applicationId }),
  });
}

export async function updateApplicationStatus(applicationId: string, status: string) {
  return apiFetch("/api/applications/status", {
    method: "PUT",
    body: JSON.stringify({ applicationId, status }),
  });
}

export async function saveApplicationNotes(applicationId: string, notes: string) {
  return apiFetch("/api/applications/notes", {
    method: "POST",
    body: JSON.stringify({ applicationId, notes }),
  });
}

export async function createManualApplication(input: {
  companyName?: string;
  jobTitle?: string;
  jobUrl: string;
  status?: "matched" | "review" | "submitted" | "interview" | "offer" | "rejected";
}) {
  return apiFetch("/api/applications/manual", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function scanJobs() {
  return apiFetch("/api/jobs/scan", { method: "POST" });
}

export async function deleteAccount() {
  return apiFetch("/api/account", { method: "DELETE" });
}

// --- Payments ---
export async function createCheckoutSession(): Promise<{ checkoutUrl: string }> {
  return apiFetch("/api/payments/create-checkout", { method: "POST" });
}
