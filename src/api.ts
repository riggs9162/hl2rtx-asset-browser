export type Kind = 'mesh' | 'texture' | 'audio';
export type Asset = { id: string; kind: Kind; name: string; path: string; chapter: string; scope: string; bytes: number; width?: number; height?: number; format?: number };
export type Detail = Asset & { contexts: {label: string; prim: string}[]; dimensions: Record<string, number> };
export type Job = { id: string; asset_id: string; purpose: string; format: string; state: string; message: string; progress: number; warnings: string[]; details: Record<string, unknown>; url: string | null; name?: string };
export type Status = { counts: Record<Kind, number>; chapters: { kind: Kind; chapter: string; count: number }[]; scanning: boolean; message: string; errors: string[]; token: string; source: string; dependencies: Record<string, boolean> };
let token = '';

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch('/api' + path, { ...options, headers: { 'Content-Type': 'application/json', 'X-App-Token': token, ...options.headers } });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(typeof body.detail === 'string' ? body.detail : `Request failed (${response.status})`);
  }
  const body = await response.json();
  if (body.token) token = body.token;
  return body;
}

export const active = (job: Job | null) => !!job && ['queued', 'running'].includes(job.state);
export const chapterName = (chapter: string) => {
  const names: Record<string, string> = {ch1_pointinsertion: 'Point Insertion', ch2_redletterday: 'A Red Letter Day', ch3_routekanal: 'Route Kanal', ch4_waterhazard: 'Water Hazard', ch5_blackmesaeast: 'Black Mesa East', ch6_ravenholm: 'Ravenholm', ch7_highway17: 'Highway 17', ch8_sandtraps: 'Sandtraps', ch9_novaprospekt: 'Nova Prospekt', ch9a_entanglement: 'Entanglement'};
  return names[chapter] || chapter.replaceAll('_', ' ');
};
