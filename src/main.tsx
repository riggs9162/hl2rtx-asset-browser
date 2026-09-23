import React, { Suspense, lazy, useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Box, Image as ImageIcon, AudioLines, Search, ArrowDownToLine, RefreshCw, FolderOpen, ChevronLeft, ChevronRight, X, Check, LoaderCircle, CircleAlert, HardDrive, SlidersHorizontal, Trash2, ExternalLink } from 'lucide-react';
import { active, api, Asset, chapterName, Detail, Job, Kind, Status } from './api';
import TextureViewer from './TextureViewer';
import { registerLibraryTools } from './webmcp';
import './style.css';

const ModelViewer = lazy(() => import('./ModelViewer'));
const icons = {mesh: Box, texture: ImageIcon, audio: AudioLines};
const labels = {mesh: 'Meshes', texture: 'Textures', audio: 'Audio'};
const defaultFormat = {mesh: 'glb', texture: 'png', audio: 'wav'};
const number = (n: unknown) => typeof n === 'number' ? n.toLocaleString() : '—';

function App() {
  const [status, setStatus] = useState<Status | null>(null);
  const [kind, setKind] = useState<Kind>('mesh');
  const [query, setQuery] = useState('');
  const [search, setSearch] = useState('');
  const [chapter, setChapter] = useState('');
  const [scope, setScope] = useState('model');
  const [offset, setOffset] = useState(0);
  const [list, setList] = useState<{items: Asset[]; total: number}>({items: [], total: 0});
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<Asset | null>(null);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [appearance, setAppearance] = useState(0);
  const [normal, setNormal] = useState(true);
  const [format, setFormat] = useState('glb');
  const [preview, setPreview] = useState<Job | null>(null);
  const [exports, setExports] = useState<Job[]>([]);
  const [error, setError] = useState('');
  const [settings, setSettings] = useState(false);
  const [retry, setRetry] = useState(0);
  const previewId = useRef<string | null>(null);
  const exportsRef = useRef<Job[]>([]);
  const queryRef = useRef<HTMLInputElement>(null);
  const settingsRef = useRef<HTMLElement>(null);
  exportsRef.current = exports;

  useEffect(registerLibraryTools, []);
  useEffect(() => {
    if (!settings) return;
    const previous = document.activeElement as HTMLElement | null;
    const dialog = settingsRef.current!;
    dialog.querySelector<HTMLButtonElement>('button')?.focus();
    const trap = (event: KeyboardEvent) => {
      if (event.key !== 'Tab') return;
      const elements = [...dialog.querySelectorAll<HTMLElement>('button:not(:disabled), select, input, a[href], summary')];
      const first = elements[0], last = elements[elements.length - 1];
      if (event.shiftKey && document.activeElement === first) {event.preventDefault(); last?.focus();}
      else if (!event.shiftKey && document.activeElement === last) {event.preventDefault(); first?.focus();}
    };
    dialog.addEventListener('keydown', trap);
    return () => {dialog.removeEventListener('keydown', trap); previous?.focus();};
  }, [settings]);

  useEffect(() => {
    const update = () => api<Status>('/status').then(setStatus).catch(e => setError(e.message));
    update(); const timer = window.setInterval(update, 3000);
    return () => clearInterval(timer);
  }, []);
  useEffect(() => {const timer = window.setTimeout(() => {setSearch(query); setOffset(0);}, 220); return () => clearTimeout(timer);}, [query]);
  useEffect(() => {
    let alive = true; setLoading(true);
    const params = new URLSearchParams({kind, q: search, chapter, scope: kind === 'mesh' ? scope : '', offset: String(offset), limit: '60'});
    api<{items: Asset[]; total: number}>('/assets?' + params).then(value => {if (alive) setList(value);}).catch(e => {if (alive) setError(e.message);}).finally(() => {if (alive) setLoading(false);});
    return () => {alive = false;};
  }, [kind, search, chapter, scope, offset, status?.message]);
  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (event.key === '/' && !(event.target instanceof HTMLInputElement)) {event.preventDefault(); queryRef.current?.focus();}
      if (event.key === 'Escape') setSettings(false);
    };
    window.addEventListener('keydown', handler); return () => window.removeEventListener('keydown', handler);
  }, []);
  useEffect(() => {
    if (!selected || !status?.token) return;
    let alive = true;
    setPreview(null);
    const previous = previewId.current;
    if (previous) api('/jobs/' + previous, {method: 'DELETE'}).catch(() => {});
    previewId.current = null;
    api<Detail>('/assets/' + selected.id).then(value => {if (alive) setDetail(value);}).catch(e => {if (alive) setError(e.message);});
    api<Job>('/assets/' + selected.id + '/jobs', {method: 'POST', body: JSON.stringify({purpose: 'preview', format: defaultFormat[selected.kind], appearance, normal})}).then(job => {
      if (!alive) {api('/jobs/' + job.id, {method: 'DELETE'}).catch(() => {}); return;}
      previewId.current = job.id; setPreview(job);
    }).catch(e => {if (alive) setError(e.message);});
    return () => {alive = false;};
  }, [selected?.id, appearance, normal, retry, status?.token]);
  useEffect(() => {
    if (!preview || !active(preview)) return;
    let alive = true;
    const timer = window.setInterval(() => {
      api<Job>('/jobs/' + preview.id).then(job => {if (alive) {setPreview(job); if (!active(job)) clearInterval(timer);}}).catch(e => {if (alive) setError(e.message);});
    }, 600);
    return () => {alive = false; clearInterval(timer);};
  }, [preview?.id]);
  useEffect(() => {
    const timer = window.setInterval(async () => {
      const running = exportsRef.current.filter(active);
      if (!running.length) return;
      const results = await Promise.all(running.map(j => api<Job>('/jobs/' + j.id).then(value => ({...value, name: j.name})).catch(() => j)));
      setExports(old => old.map(job => results.find(r => r.id === job.id) || job));
    }, 900);
    return () => clearInterval(timer);
  }, []);

  function select(asset: Asset) {
    if (asset.id === selected?.id) return;
    setSelected(asset); setDetail(null); setAppearance(0); setNormal(true); setFormat(defaultFormat[asset.kind]); setError('');
  }
  function switchKind(value: Kind) {
    setKind(value); setChapter(''); setOffset(0); setQuery(''); setSearch(''); setSelected(null); setDetail(null); setPreview(null);
    if (previewId.current) api('/jobs/' + previewId.current, {method: 'DELETE'}).catch(() => {});
    previewId.current = null;
  }
  async function exportAsset() {
    if (!selected) return;
    try {
      const job = await api<Job>('/assets/' + selected.id + '/jobs', {method: 'POST', body: JSON.stringify({purpose: 'export', format, appearance, normal})});
      setExports(old => [{...job, name: selected.name}, ...old.filter(j => j.id !== job.id)].slice(0, 20));
    } catch (e) {setError((e as Error).message);}
  }
  async function cancel(job: Job) {
    try {
      await api('/jobs/' + job.id, {method: 'DELETE'});
      if (job.id === preview?.id) setPreview({...job, state: 'cancelled', message: 'Preview cancelled'});
      setExports(old => old.map(j => j.id === job.id ? {...j, state: 'cancelled', message: 'Cancelled'} : j));
    } catch (e) {setError((e as Error).message);}
  }
  const Icon = icons[kind];
  const stats = preview?.details || {};
  const chapters = status?.chapters.filter(c => c.kind === kind) || [];
  const busyExport = exports.some(j => j.asset_id === selected?.id && active(j));

  return <div className="app-shell">
    <header className="topbar"><div className="brand"><div className="lambda">λ</div><div><strong>HALF-LIFE 2 <em>RTX</em></strong><span>ASSET BROWSER</span></div></div><div className="topbar-right"><span className="local-badge"><HardDrive size={14}/> LOCAL LIBRARY</span><button className="icon-button" title="Library settings" aria-label="Library settings" onClick={() => setSettings(true)}><SlidersHorizontal size={19}/></button></div></header>
    <div className="workspace">
      <aside className="library">
        <div className="library-heading"><div><p className="eyebrow">YOUR COLLECTION</p><h1>Asset library</h1></div><button className="icon-button" aria-label="Rescan library" disabled={status?.scanning} onClick={() => api('/rescan', {method: 'POST'}).catch(e => setError(e.message))}><RefreshCw size={17} className={status?.scanning ? 'spin' : ''}/></button></div>
        <nav className="tabs" aria-label="Asset types">{(['mesh','texture','audio'] as Kind[]).map(type => {const TabIcon = icons[type]; return <button key={type} className={kind === type ? 'selected' : ''} onClick={() => switchKind(type)}><TabIcon size={17}/>{labels[type]}<span>{number(status?.counts[type])}</span></button>;})}</nav>
        <div className="search"><Search size={17}/><input ref={queryRef} aria-label="Search assets" placeholder={`Search ${labels[kind].toLowerCase()}…`} value={query} onChange={e => setQuery(e.target.value)}/>{query ? <button aria-label="Clear search" onClick={() => setQuery('')}><X size={15}/></button> : <kbd>/</kbd>}</div>
        <div className="filters"><label><FolderOpen size={15}/><select aria-label="Chapter or folder" value={chapter} onChange={e => {setChapter(e.target.value); setOffset(0);}}><option value="">{kind === 'audio' ? 'All sound folders' : 'All chapters'}</option>{chapters.map(c => <option key={c.chapter} value={c.chapter}>{chapterName(c.chapter)} ({c.count})</option>)}</select></label>{kind === 'mesh' && <select aria-label="Model or scene filter" value={scope} onChange={e => {setScope(e.target.value); setOffset(0);}}><option value="model">Models</option><option value="scene">Scene layers</option><option value="">All USD</option></select>}</div>
        <div className="list-heading"><span>{number(list.total)} {labels[kind].toLowerCase()}</span><span>{loading ? 'Loading…' : 'NAME A–Z'}</span></div>
        <div className="asset-list" aria-label="Assets" aria-busy={loading}>{list.items.map(asset => <button className={'asset-row ' + (selected?.id === asset.id ? 'chosen' : '')} key={asset.id} onClick={() => select(asset)}><div className={'asset-icon ' + kind}><Icon size={23} strokeWidth={1.4}/></div><div className="asset-info"><strong>{asset.name}</strong><span>{chapterName(asset.chapter)}</span></div><span className="asset-ext">{kind === 'texture' ? asset.width ? `${asset.width / 1024 >= 1 ? Math.round(asset.width / 1024) + 'K' : asset.width}` : 'IMG' : kind === 'audio' ? asset.path.split('.').pop()?.toUpperCase() : asset.path.split('.').pop()?.toUpperCase()}</span></button>)}{!list.items.length && <div className="list-empty"><Search size={28}/><strong>{status?.scanning ? 'Reading your library' : 'No matching assets'}</strong><p>{status?.scanning ? 'Files appear when metadata indexing finishes.' : 'Try another search or folder.'}</p></div>}</div>
        <footer className="list-footer"><span>{list.total ? `${offset + 1}–${Math.min(offset + 60, list.total)} of ${number(list.total)}` : '0 assets'}</span><div><button aria-label="Previous page" disabled={!offset} onClick={() => setOffset(Math.max(0, offset - 60))}><ChevronLeft size={18}/></button><button aria-label="Next page" disabled={offset + 60 >= list.total} onClick={() => setOffset(offset + 60)}><ChevronRight size={18}/></button></div></footer>
      </aside>
      <main className="main-area">
        {error && <div role="alert" className="error-banner"><CircleAlert size={17}/><span>{error}</span><button aria-label="Dismiss error" onClick={() => setError('')}><X size={16}/></button></div>}
        {selected ? <>
          <div className="asset-title"><div><p className="eyebrow">{labels[kind].toUpperCase()} <span>/</span> {chapterName(selected.chapter).toUpperCase()}</p><h2>{selected.name}</h2></div><span className="format-badge">{selected.path.split('.').pop()?.toUpperCase()}</span></div>
          <div className="preview-area">
            {preview?.state === 'done' && preview.url ? kind === 'mesh' ? <Suspense fallback={<div className="preview-message"><LoaderCircle className="spin"/>Loading viewer</div>}><ModelViewer url={preview.url}/></Suspense> : kind === 'texture' ? <TextureViewer url={preview.url}/> : <div className="audio-stage"><div className="audio-orbit"><AudioLines size={76} strokeWidth={1}/></div><p className="eyebrow">AUDIO PREVIEW</p><h3>{selected.name}</h3><audio key={preview.url} controls preload="metadata" src={preview.url}/><span className="muted">Original audio · No automatic playback</span></div> : <div className="preview-message">{!preview || active(preview) ? <><div className="loading-orbit"><LoaderCircle size={34} className="spin"/></div><h3>{preview?.message || 'Preparing preview'}</h3><p>Only this asset and its dependencies are being read.</p><div className="progress"><i style={{width: `${Math.max(5, preview?.progress || 0)}%`}}/></div>{preview && <button className="text-button" onClick={() => cancel(preview)}>Cancel preview</button>}</> : <><CircleAlert size={34}/><h3>{preview.state === 'cancelled' ? 'Preview cancelled' : 'Preview unavailable'}</h3><p className="error-detail">{preview.message}</p><button onClick={() => setRetry(v => v + 1)}>Try again</button></>}</div>}
          </div>
          <div className="inspector"><div className="asset-metrics">{kind === 'mesh' ? <><div><span>VERTICES</span><strong>{number(stats.vertices)}</strong></div><div><span>TRIANGLES</span><strong>{number(stats.triangles)}</strong></div><div><span>MATERIALS</span><strong>{Array.isArray(stats.materials) ? stats.materials.length : '—'}</strong></div><div><span>SKELETONS</span><strong>{number(stats.skeletons)}</strong></div></> : kind === 'texture' ? <><div><span>ORIGINAL SIZE</span><strong>{selected.width ? `${selected.width} × ${selected.height}` : 'Source image'}</strong></div><div><span>EXPORT</span><strong>Lossless PNG</strong></div></> : <><div><span>SOURCE FORMAT</span><strong>{selected.path.split('.').pop()?.toUpperCase()}</strong></div><div><span>FILE SIZE</span><strong>{(selected.bytes / 1024).toFixed(0)} KB</strong></div></>}</div>
            <div className="export-controls">{kind === 'mesh' && !!detail?.contexts.length && <label>Appearance<select aria-label="Model appearance" value={appearance} onChange={e => setAppearance(Number(e.target.value))}>{detail.contexts.map((c, i) => <option key={i} value={i}>{chapterName(c.label.replaceAll(' ', '_').replace(/_(props|skinned|decals|textures|lights|particles)$/, ''))} · Variant {i + 1}</option>)}<option value={-1}>Source model</option></select></label>}{kind === 'texture' && /normal|\.n\.rtex/i.test(selected.path) && <label className="normal-toggle"><input type="checkbox" checked={normal} onChange={e => setNormal(e.target.checked)}/> Blender normals</label>}<label>Download format<select aria-label="Export format" value={format} onChange={e => setFormat(e.target.value)}>{(kind === 'mesh' ? [['glb','GLB · embedded textures'],['gltf','glTF · ZIP package']] : kind === 'texture' ? [['png','PNG · full resolution']] : [['wav','WAV · lossless PCM'],['mp3','MP3 · high quality']]).map(([value, text]) => <option key={value} value={value}>{text}</option>)}</select></label><button className="export-button" disabled={busyExport || !status?.token} onClick={exportAsset}>{busyExport ? <LoaderCircle size={18} className="spin"/> : <ArrowDownToLine size={18}/>}Export {format === 'gltf' ? 'glTF' : format.toUpperCase()}</button></div>
            <div className="source-path" title={selected.path}><FolderOpen size={14}/><span>{selected.path}</span></div>
            {!!preview?.warnings.length && <details className="warnings"><summary><CircleAlert size={15}/>{preview.warnings.length} conversion note{preview.warnings.length > 1 ? 's' : ''}</summary><ul>{preview.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul></details>}
          </div>
        </> : <div className="welcome"><div className="welcome-grid"><div className="wire-cube"><Box size={100} strokeWidth={0.7}/></div></div><p className="eyebrow">HALF-LIFE 2 RTX</p><h2>A closer look<br/>at City 17.</h2><p>Choose an asset to explore its details.<br/>Take it into your next project when you’re ready.</p><div className="welcome-formats"><span><Box size={16}/> GLB / glTF</span><span><ImageIcon size={16}/> PNG</span><span><AudioLines size={16}/> WAV / MP3</span></div><div className="on-demand"><span className="small-dot"/> Preview on demand. Export when you choose.</div></div>}
        {!!exports.length && <section className="exports"><div className="exports-title"><span>EXPORTS <b>{exports.length}</b></span><button className="text-button" onClick={() => setExports(old => old.filter(active))}>Clear finished</button></div>{exports.map(job => <div className="export-job" key={job.id}><div className={'job-icon ' + job.state}>{active(job) ? <LoaderCircle size={17} className="spin"/> : job.state === 'done' ? <Check size={17}/> : <CircleAlert size={17}/>}</div><div className="job-name"><strong>{job.name}</strong><span>{job.state === 'error' ? job.message : job.state === 'done' ? `${job.format.toUpperCase()} ready${job.warnings.length ? ' · ' + job.warnings.length + ' conversion notes' : ''}` : job.message}</span>{job.state === 'error' || job.warnings.length > 0 ? <details><summary>Details</summary><p>{job.state === 'error' ? job.message : job.warnings.join('\n')}</p></details> : null}</div>{active(job) ? <><span className="job-progress">{job.progress}%</span><button className="icon-button" aria-label="Cancel export" onClick={() => cancel(job)}><X size={17}/></button></> : job.state === 'done' && job.url ? <a className="download" href={job.url} download><ArrowDownToLine size={16}/>Download</a> : null}</div>)}</section>}
      </main>
    </div>
    <footer className="statusbar"><span><span className={'small-dot ' + (status?.scanning ? 'orange' : '')}/>{status?.scanning ? status.message : 'Local files · Read-only source'}</span><span>{number(Object.values(status?.counts || {}).reduce((a, b) => a + b, 0))} assets <span className="divider">/</span> ON-DEMAND CONVERSION</span></footer>
    {settings && <div className="modal-backdrop" onClick={() => setSettings(false)}><section ref={settingsRef} className="settings" role="dialog" aria-modal="true" aria-label="Library settings" onClick={e => e.stopPropagation()}><div className="settings-heading"><h2>Library settings</h2><button aria-label="Close settings" onClick={() => setSettings(false)}><X size={20}/></button></div><p className="eyebrow">SOURCE FOLDER</p><p className="settings-path">{status?.source}</p><p>Game files are read-only. Sounds also include the neighboring game folders and archives.</p><div className="dependency-list">{Object.entries(status?.dependencies || {}).map(([name, available]) => <div key={name}><span>{name === 'extractor' ? 'RTX IO texture decoder' : name === 'ffmpeg' ? 'Audio converter' : 'Blender'}</span><b className={available ? '' : 'missing'}>{available ? 'Ready' : 'Missing'}</b></div>)}</div><div className="cache-info"><strong>Temporary storage</strong><p>Previews: up to 2 GB. Exports: up to 10 GB, expiring after 24 hours. Your downloaded files are unaffected.</p></div><div className="settings-actions"><button onClick={() => api('/rescan', {method: 'POST'}).then(() => setSettings(false)).catch(e => setError(e.message))}><RefreshCw size={16}/>Rescan library</button><button onClick={() => api('/cache', {method: 'DELETE'}).then(() => {setSettings(false); setPreview(null); setExports([]); setSelected(null);}).catch(e => {setSettings(false); setError(e.message);})}><Trash2 size={16}/>Clear cache</button></div>{!!status?.errors.length && <details><summary>Indexing notes ({status.errors.length})</summary><ul>{status.errors.map((e, i) => <li key={i}>{e}</li>)}</ul></details>}</section></div>}
  </div>;
}

createRoot(document.getElementById('root')!).render(<App/>);
