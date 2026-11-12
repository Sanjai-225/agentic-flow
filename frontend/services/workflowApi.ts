import { WorkflowResponse } from "@/types/workflow";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/+$/, "") || "http://localhost:8000";

/**
 * Generate a workflow from a natural language prompt
 */
export async function generateWorkflow(
  prompt: string
): Promise<WorkflowResponse> {
  const url = `${API_BASE_URL}/api/workflows/generate`;

  let response: Response;
  try {
    response = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ prompt }),
    });
  } catch (err: any) {
    throw new Error(
      `Unable to connect to workflow backend at ${API_BASE_URL}. Check if the server is running. (${err?.message || "Network Error"})`
    );
  }

  if (!response.ok) {
    let errorMessage = `Server error (${response.status} ${response.statusText})`;
    try {
      const errorJson = await response.json();
      if (errorJson?.detail) {
        errorMessage =
          typeof errorJson.detail === "string"
            ? errorJson.detail
            : JSON.stringify(errorJson.detail);
      } else if (errorJson?.message) {
        errorMessage = errorJson.message;
      } else if (errorJson?.error) {
        errorMessage = errorJson.error;
      }
    } catch {
      const errorText = await response.text().catch(() => "");
      if (errorText) {
        errorMessage = errorText;
      }
    }
    throw new Error(errorMessage);
  }

  const data: WorkflowResponse = await response.json();
  return data;
}

/**
 * Check backend health status
 */
export async function checkBackendHealth(): Promise<boolean> {
  try {
    const res = await fetch(`${API_BASE_URL}/health`);
    return res.ok;
  } catch {
    return false;
  }
}
