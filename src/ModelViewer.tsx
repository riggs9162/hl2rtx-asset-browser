import { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { Box, Maximize, Pause, Play, RotateCcw } from 'lucide-react';

type MaterialInfo = { name: string; color: string; roughness: number; metalness: number; opacity: number; maps: string[] };

export default function ModelViewer({ url }: { url: string }) {
  const element = useRef<HTMLDivElement>(null);
  const actions = useRef<{frame: () => void; wire: (enabled: boolean) => void; animate: (index: number, playing: boolean) => void} | null>(null);
  const [wire, setWire] = useState(false);
  const [error, setError] = useState('');
  const [materials, setMaterials] = useState<MaterialInfo[]>([]);
  const [material, setMaterial] = useState(0);
  const [clips, setClips] = useState<string[]>([]);
  const [clip, setClip] = useState(0);
  const [playing, setPlaying] = useState(false);

  useEffect(() => {
    const host = element.current!;
    setError(''); setMaterials([]); setWire(false); setClips([]); setPlaying(false); setMaterial(0);
    let renderer: THREE.WebGLRenderer;
    try { renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true }); }
    catch { setError('3D preview needs WebGL. Enable browser hardware acceleration, or download the model to view it in Blender.'); return; }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.5));
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.1;
    host.appendChild(renderer.domElement);
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(35, 1, 0.01, 10000);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    const pmrem = new THREE.PMREMGenerator(renderer);
    const room = new RoomEnvironment();
    const environment = pmrem.fromScene(room, 0.04);
    room.dispose(); pmrem.dispose();
    scene.environment = environment.texture;
    scene.add(new THREE.HemisphereLight(0xd7e9ff, 0x40332b, 1.5));
    const light = new THREE.DirectionalLight(0xffffff, 2.4);
    light.position.set(5, 10, 5); scene.add(light);
    let root: THREE.Group | undefined;
    let mixer: THREE.AnimationMixer | undefined;
    let animationClips: THREE.AnimationClip[] = [];
    let animating = false;
    let disposed = false;
    let dirty = true;
    let grid: THREE.GridHelper | undefined;
    const frame = () => {
      if (!root) return;
      const box = new THREE.Box3().setFromObject(root);
      const center = box.getCenter(new THREE.Vector3());
      const size = box.getSize(new THREE.Vector3());
      const distance = Math.max(size.x, size.y, size.z, 0.01) / (2 * Math.tan(THREE.MathUtils.degToRad(17.5))) * 1.5;
      controls.target.copy(center);
      camera.position.copy(center).add(new THREE.Vector3(0.95, 0.65, 1.5).normalize().multiplyScalar(distance));
      camera.near = distance / 1000; camera.far = distance * 100;
      camera.updateProjectionMatrix(); controls.update();
      dirty = true;
    };
    const disposeObject = (obj: THREE.Object3D) => obj.traverse(child => {
      const mesh = child as THREE.Mesh;
      mesh.geometry?.dispose();
      if (mesh.material) for (const mat of Array.isArray(mesh.material) ? mesh.material : [mesh.material]) {
        for (const value of Object.values(mat)) if (value instanceof THREE.Texture) value.dispose();
        mat.dispose();
      }
    });
    const loader = new GLTFLoader();
    loader.load(url, gltf => {
      if (disposed) { disposeObject(gltf.scene); return; }
      root = gltf.scene; scene.add(root);
      const box = new THREE.Box3().setFromObject(root);
      const size = box.getSize(new THREE.Vector3()).length() || 1;
      grid = new THREE.GridHelper(size * 2.5, 30, 0x55514a, 0x303335);
      grid.position.copy(box.getCenter(new THREE.Vector3())); grid.position.y = box.min.y - size * 0.008;
      scene.add(grid);
      const seen = new Set<THREE.Material>();
      root.traverse(child => {
        const mesh = child as THREE.Mesh;
        if (mesh.material) (Array.isArray(mesh.material) ? mesh.material : [mesh.material]).forEach(m => seen.add(m));
      });
      setMaterials([...seen].map(m => {
        const mat = m as THREE.MeshStandardMaterial;
        return { name: mat.name || 'Unnamed material', color: '#' + (mat.color?.getHexString() || 'ffffff'), roughness: mat.roughness ?? 0, metalness: mat.metalness ?? 0, opacity: mat.opacity, maps: ['map', 'normalMap', 'roughnessMap', 'metalnessMap', 'emissiveMap'].filter(key => (mat as unknown as Record<string, unknown>)[key]).map(s => s === 'map' ? 'Base color' : s.replace('Map', '')) };
      }));
      animationClips = gltf.animations;
      if (animationClips.length) { mixer = new THREE.AnimationMixer(root); setClips(animationClips.map((c, i) => c.name || `Animation ${i + 1}`)); }
      frame();
    }, undefined, () => { if (!disposed) setError('Could not load this preview. Try generating it again.'); });
    actions.current = {frame, wire: enabled => {dirty = true; root?.traverse(child => {
      const mesh = child as THREE.Mesh;
      if (mesh.material) for (const material of Array.isArray(mesh.material) ? mesh.material : [mesh.material]) (material as THREE.MeshStandardMaterial).wireframe = enabled;
    });}, animate: (index, play) => {
      mixer?.stopAllAction();
      if (animationClips[index]) mixer?.clipAction(animationClips[index]).play();
      animating = play;
      dirty = true;
    }};
    const resize = () => { const w = host.clientWidth, h = host.clientHeight; renderer.setSize(w, h); camera.aspect = w / Math.max(1, h); camera.updateProjectionMatrix(); dirty = true; };
    const observer = new ResizeObserver(resize); observer.observe(host); resize();
    const clock = new THREE.Clock();
    let frameId = 0;
    const render = () => {
      frameId = requestAnimationFrame(render);
      const delta = Math.min(clock.getDelta(), 0.1);
      if (document.hidden) return;
      const changed = controls.update();
      if (animating) mixer?.update(delta);
      if (changed || dirty || animating) {renderer.render(scene, camera); dirty = false;}
    };
    render();
    return () => {
      disposed = true; cancelAnimationFrame(frameId); observer.disconnect(); controls.dispose(); actions.current = null;
      mixer?.stopAllAction(); if (root) disposeObject(root); if (grid) { grid.geometry.dispose(); (grid.material as THREE.Material).dispose(); }
      environment.dispose(); renderer.dispose(); renderer.forceContextLoss(); renderer.domElement.remove();
    };
  }, [url]);

  const selected = materials[material];
  return <div className="model-stage">
    <div ref={element} className="three-canvas" aria-label="Interactive model preview. Drag to orbit, scroll to zoom." />
    {error && <div className="viewer-error">{error}</div>}
    <div className="viewport-label"><span className="live-dot" /> PERSPECTIVE <span className="divider">/</span> LIT</div>
    <div className="viewer-tools">
      <button title="Frame model" aria-label="Frame model" onClick={() => actions.current?.frame()}><Maximize size={17}/></button>
      <button className={wire ? 'on' : ''} aria-pressed={wire} title="Wireframe" onClick={() => {setWire(!wire); actions.current?.wire(!wire);}}><Box size={17}/><span>Wireframe</span></button>
      <button title="Reset camera" aria-label="Reset camera" onClick={() => actions.current?.frame()}><RotateCcw size={17}/></button>
    </div>
    <div className="orbit-hint">Drag to orbit <span>·</span> Scroll to zoom <span>·</span> Right-drag to pan</div>
    {!!clips.length && <div className="animation-bar"><select aria-label="Animation" value={clip} onChange={e => {const i = Number(e.target.value); setClip(i); actions.current?.animate(i, playing);}}>{clips.map((c, i) => <option value={i} key={i}>{c}</option>)}</select><button aria-label={playing ? "Pause animation" : "Play animation"} onClick={() => {setPlaying(!playing); actions.current?.animate(clip, !playing);}}>{playing ? <Pause size={16}/> : <Play size={16}/>}</button></div>}
    {!!materials.length && <details className="materials"><summary>Materials <span>{materials.length}</span></summary><select aria-label="Inspect material" value={material} onChange={e => setMaterial(Number(e.target.value))}>{materials.map((m, i) => <option value={i} key={i}>{m.name}</option>)}</select>{selected && <><div className="material-values"><i style={{background: selected.color}}/> Roughness {selected.roughness.toFixed(2)} · Metal {selected.metalness.toFixed(2)} · Opacity {selected.opacity.toFixed(2)}</div><div className="tags">{selected.maps.map(m => <span key={m}>{m}</span>)}</div></>}</details>}
  </div>;
}
