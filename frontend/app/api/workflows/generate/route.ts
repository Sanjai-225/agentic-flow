import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";

export async function POST(request: NextRequest) {
  const backendBase = process.env.BACKEND_URL || "http://127.0.0.1:8000";
  const body = await request.text();

  try {
    const targetUrl = new URL("/api/workflows/generate", backendBase);
    const response = await fetch(targetUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body,
    });

    const data = await response.json();
    return NextResponse.json(data, { status: response.status });
  } catch (err: any) {
    return NextResponse.json(
      {
        detail: `Failed to connect to backend service at ${backendBase}: ${err?.message || "Unknown error"}`,
      },
      { status: 502 }
    );
  }
}

