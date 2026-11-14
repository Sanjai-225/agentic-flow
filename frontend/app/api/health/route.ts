import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

export async function GET() {
  const backendBase = process.env.BACKEND_URL || "http://127.0.0.1:8000";

  try {
    const targetUrl = new URL("/health", backendBase);
    const response = await fetch(targetUrl);
    const data = await response.json();
    return NextResponse.json(data, { status: response.status });
  } catch (err: any) {
    return NextResponse.json(
      { status: "unhealthy", detail: err?.message || "Unknown error" },
      { status: 502 }
    );
  }
}

