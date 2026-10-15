export class ApiError extends Error {}

async function handle<T>(r: Response): Promise<T> {
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`;
    try {
      const body = await r.json();
      if (body?.detail) msg = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* not JSON */
    }
    throw new ApiError(msg);
  }
  return r.json() as Promise<T>;
}

export const api = {
  get: <T = any>(url: string) => fetch(url).then((r) => handle<T>(r)),
  post: <T = any>(url: string, body?: unknown) =>
    fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    }).then((r) => handle<T>(r)),
  put: <T = any>(url: string, body: unknown) =>
    fetch(url, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).then(
      (r) => handle<T>(r),
    ),
  del: <T = any>(url: string) => fetch(url, { method: "DELETE" }).then((r) => handle<T>(r)),
  upload: <T = any>(url: string, form: FormData) => fetch(url, { method: "POST", body: form }).then((r) => handle<T>(r)),
  download: async (url: string, body: unknown, fallbackName: string) => {
    const r = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!r.ok) throw new ApiError(`${r.status} ${r.statusText}`);
    const blob = await r.blob();
    const cd = r.headers.get("Content-Disposition") || "";
    const name = /filename="([^"]+)"/.exec(cd)?.[1] || fallbackName;
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = name;
    a.click();
    URL.revokeObjectURL(a.href);
  },
};
