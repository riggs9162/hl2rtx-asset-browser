import { useEffect, useRef, useState } from 'react';
import { Minus, Plus, Maximize } from 'lucide-react';

export default function TextureViewer({ url }: { url: string }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const container = useRef<HTMLDivElement>(null);
  const original = useRef<ImageData | null>(null);
  const [channel, setChannel] = useState('RGBA');
  const [zoom, setZoom] = useState(1);
  const [size, setSize] = useState('');
  const [dimensions, setDimensions] = useState([1, 1]);
  const [viewport, setViewport] = useState([1, 1]);
  useEffect(() => {
    const element = container.current!;
    const observer = new ResizeObserver(() => setViewport([element.clientWidth - 60, element.clientHeight - 40]));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    let alive = true;
    const image = new Image();
    image.onload = () => {
      if (!alive || !canvas.current) return;
      const c = canvas.current; c.width = image.width; c.height = image.height;
      const context = c.getContext('2d', {willReadFrequently: true})!;
      context.drawImage(image, 0, 0); original.current = context.getImageData(0, 0, c.width, c.height);
      setSize(`${image.width} × ${image.height}`); setDimensions([image.width, image.height]); setChannel('RGBA'); setZoom(1);
    };
    image.src = url;
    return () => {alive = false; original.current = null;};
  }, [url]);
  useEffect(() => {
    if (!original.current || !canvas.current) return;
    const data = new ImageData(new Uint8ClampedArray(original.current.data), original.current.width, original.current.height);
    if (channel !== 'RGBA') {
      for (let i = 0; i < data.data.length; i += 4) {
        if (channel !== 'RGB') {const value = data.data[i + ['R','G','B','A'].indexOf(channel)]; data.data[i] = data.data[i + 1] = data.data[i + 2] = value;}
        data.data[i + 3] = 255;
      }
    }
    canvas.current.getContext('2d')!.putImageData(data, 0, 0);
  }, [channel, size]);
  const fit = Math.max(0.01, Math.min(viewport[0] / dimensions[0], viewport[1] / dimensions[1], 1));
  const width = dimensions[0] * fit * zoom, height = dimensions[1] * fit * zoom;
  return <div className="texture-stage"><div className="texture-controls"><div className="segmented">{['RGBA','RGB','R','G','B','A'].map(c => <button key={c} className={channel === c ? 'on' : ''} onClick={() => setChannel(c)}>{c}</button>)}</div><div className="zoom-controls"><button aria-label="Zoom out" onClick={() => setZoom(v => Math.max(0.25, v / 1.4))}><Minus size={16}/></button><span>{Math.round(zoom * 100)}%</span><button aria-label="Zoom in" onClick={() => setZoom(v => Math.min(8, v * 1.4))}><Plus size={16}/></button><button aria-label="Fit texture" onClick={() => setZoom(1)}><Maximize size={16}/></button></div></div><div className="texture-scroll" ref={container}><div className="texture-center" style={{width: Math.max(viewport[0], width), height: Math.max(viewport[1], height)}}><canvas ref={canvas} style={{width, height, maxWidth: 'none', maxHeight: 'none'}}/></div></div><div className="texture-size">Preview {size} <span>·</span> Export uses original resolution</div></div>;
}
