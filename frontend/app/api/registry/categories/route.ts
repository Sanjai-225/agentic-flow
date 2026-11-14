import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";

export async function GET(_request: NextRequest) {
  const backendBase = process.env.BACKEND_URL || "http://127.0.0.1:8000";

  try {
    const targetUrl = new URL("/api/registry/categories", backendBase);
    const response = await fetch(targetUrl.toString(), {
      method: "GET",
      headers: {
        "Accept": "application/json",
      },
      cache: "no-store",
    });

    const data = await response.json();
    return NextResponse.json(data, { status: response.status });
  } catch (err: any) {
    return NextResponse.json(
      {
        detail: `Failed to connect to backend registry at ${backendBase}: ${err?.message || "Unknown error"}`,
      },
      { status: 502 }
    );
  }
}
