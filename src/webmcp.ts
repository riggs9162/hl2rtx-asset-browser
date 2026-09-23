import { api } from './api';

type Tool = { name: string; title: string; description: string; inputSchema: object; annotations: {readOnlyHint: boolean; untrustedContentHint: boolean}; execute: (input: unknown) => Promise<unknown> };

export function registerLibraryTools() {
  const context = (document as Document & {modelContext?: {registerTool: (tool: Tool, options: {signal: AbortSignal}) => void | Promise<void>}}).modelContext;
  if (!context?.registerTool) return () => {};
  const lifecycle = new AbortController();
  const tool: Tool = {
    name: 'search_asset_library', title: 'Search local assets',
    description: 'Search the indexed Half-Life 2 RTX library. Returns names and asset IDs without converting, previewing, or exporting files.',
    inputSchema: {type: 'object', properties: {kind: {type: 'string', enum: ['mesh', 'texture', 'audio']}, query: {type: 'string', maxLength: 200}}, required: ['kind'], additionalProperties: false},
    annotations: {readOnlyHint: true, untrustedContentHint: true},
    async execute(input) {
      if (!input || typeof input !== 'object') throw new Error('Expected a search object.');
      const value = input as Record<string, unknown>;
      if (!['mesh', 'texture', 'audio'].includes(String(value.kind)) || Object.keys(value).some(k => !['kind','query'].includes(k))) throw new Error('Invalid asset search.');
      if (value.query !== undefined && (typeof value.query !== 'string' || value.query.length > 200)) throw new Error('Query must be a string of at most 200 characters.');
      return api('/assets?' + new URLSearchParams({kind: String(value.kind), q: String(value.query || ''), limit: '60'}));
    }
  };
  try {Promise.resolve(context.registerTool(tool, {signal: lifecycle.signal})).catch(() => {});} catch {}
  return () => lifecycle.abort();
}
