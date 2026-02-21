import axios from "axios";
const api = axios.create({ baseURL: "/api", timeout: 300000 });

export async function uploadCSV(file: File) {
  const fd = new FormData(); fd.append("file", file);
  return (await api.post("/upload", fd, { headers: { "Content-Type": "multipart/form-data" } })).data;
}
export async function getTables() { return (await api.get("/tables")).data; }

export function chatStream(query: string, tables: string[]) {
  const controller = new AbortController();
  return new CustomSSE("/api/chat", { query, tables }, controller);
}

class CustomSSE {
  private controller: AbortController;
  onmessage: ((event: string, data: any) => void) | null = null;
  onerror: ((err: any) => void) | null = null;
  constructor(private url: string, private body: any, controller: AbortController) {
    this.controller = controller; this.connect();
  }
  private async connect() {
    try {
      const res = await fetch(this.url, { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(this.body), signal: this.controller.signal });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const reader = res.body?.getReader();
      if (!reader) throw new Error("No stream");
      const decoder = new TextDecoder(); let buffer = "", eventType = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n"); buffer = lines.pop() || "";
        for (const line of lines) {
          if (line.startsWith("event: ")) eventType = line.slice(7).trim();
          else if (line.startsWith("data: ") && this.onmessage) {
            try { this.onmessage(eventType, JSON.parse(line.slice(6))); } catch {}
          }
        }
      }
    } catch (err: any) { if (err.name !== "AbortError" && this.onerror) this.onerror(err); }
  }
  close() { this.controller.abort(); }
}
