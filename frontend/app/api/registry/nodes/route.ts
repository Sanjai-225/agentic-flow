import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  const backendBase = process.env.BACKEND_URL || "http://127.0.0.1:8000";
  const searchParams = request.nextUrl.searchParams;
  const category = searchParams.get("category");

  try {
    const targetUrl = new URL("/api/registry/nodes", backendBase);
    if (category) {
      targetUrl.searchParams.set("category", category);
    }

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
