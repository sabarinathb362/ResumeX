/**
 * A quiet three.js backdrop for the upload stage: a sparse field of points drifting as a slow wave,
 * faded out toward the bottom by a CSS mask.
 *
 * Kept cheap on purpose (the GPU is shared with the local models):
 *   - this file and three.js are a separate chunk, loaded only after the upload stage has painted
 *   - ~2,600 points, one draw call, no antialiasing, device-pixel-ratio capped at 1.5, ~30 fps
 *   - rendering stops when the tab is hidden or the canvas is off screen, and everything is
 *     disposed on unmount (the stage unmounts it as soon as an analysis starts)
 *   - not rendered at all when the user prefers reduced motion (the parent checks)
 */
import { useEffect, useRef, useState } from 'react';
import {
  BufferAttribute, BufferGeometry, Color, PerspectiveCamera, Points, Scene, ShaderMaterial, WebGLRenderer,
} from 'three';

const COLS = 72;
const ROWS = 36;

const VERT = /* glsl */`
  uniform float uTime;
  uniform float uSize;
  attribute float aSeed;
  varying float vAlpha;
  void main() {
    vec3 p = position;
    p.y += sin(p.x * 0.55 + uTime * 0.35) * 0.32 + cos(p.z * 0.7 + uTime * 0.27 + aSeed) * 0.22;
    vec4 mv = modelViewMatrix * vec4(p, 1.0);
    gl_Position = projectionMatrix * mv;
    gl_PointSize = max(uSize * (6.0 / -mv.z), uSize * 0.42);
    vAlpha = smoothstep(26.0, 6.0, -mv.z);
  }`;

const FRAG = /* glsl */`
  uniform vec3 uColor;
  uniform float uOpacity;
  varying float vAlpha;
  void main() {
    float d = length(gl_PointCoord - 0.5);
    if (d > 0.5) discard;
    gl_FragColor = vec4(uColor, uOpacity * vAlpha * smoothstep(0.5, 0.2, d));
  }`;

function themeColor() {
  const v = getComputedStyle(document.documentElement).getPropertyValue('--accent-primary').trim();
  return new Color(v || '#2C3E20');
}

export default function BackdropField() {
  const hostRef = useRef(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const host = hostRef.current;
    let renderer;
    try {
      renderer = new WebGLRenderer({ antialias: false, alpha: true, powerPreference: 'low-power' });
    } catch {
      return undefined;                       // no WebGL: the page simply has no backdrop
    }
    const dpr = Math.min(window.devicePixelRatio || 1, 1.5);
    renderer.setPixelRatio(dpr);
    renderer.setClearColor(0x000000, 0);
    host.appendChild(renderer.domElement);

    const scene = new Scene();
    const camera = new PerspectiveCamera(42, 1, 0.1, 60);
    // Looking down past the plane puts the far rows near the top of the canvas and the near rows
    // about three quarters down, where the CSS mask has faded them out.
    camera.position.set(0, 2.2, 8);
    camera.lookAt(0, -2.6, -6);

    const positions = new Float32Array(COLS * ROWS * 3);
    const seeds = new Float32Array(COLS * ROWS);
    let i = 0;
    for (let r = 0; r < ROWS; r++) {
      for (let c = 0; c < COLS; c++, i++) {
        positions[i * 3] = (c / (COLS - 1) - 0.5) * 34;
        positions[i * 3 + 1] = 0;
        positions[i * 3 + 2] = -r * 0.62 + 4;
        seeds[i] = Math.random() * 6.283;
      }
    }
    const geometry = new BufferGeometry();
    geometry.setAttribute('position', new BufferAttribute(positions, 3));
    geometry.setAttribute('aSeed', new BufferAttribute(seeds, 1));
    const dark = () => document.documentElement.dataset.theme === 'dark';
    const material = new ShaderMaterial({
      vertexShader: VERT,
      fragmentShader: FRAG,
      transparent: true,
      depthWrite: false,
      uniforms: {
        uTime: { value: 0 },
        uSize: { value: 4.2 * dpr },
        uColor: { value: themeColor() },
        uOpacity: { value: dark() ? 0.6 : 0.5 },
      },
    });
    scene.add(new Points(geometry, material));

    const resize = () => {
      const { clientWidth: w, clientHeight: h } = host;
      if (!w || !h) return;
      renderer.setSize(w, h, false);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
    };
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(host);

    // Follow the theme toggle.
    const mo = new MutationObserver(() => {
      material.uniforms.uColor.value = themeColor();
      material.uniforms.uOpacity.value = dark() ? 0.6 : 0.5;
    });
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });

    let visible = true;
    const io = new IntersectionObserver(([e]) => { visible = e.isIntersecting; });
    io.observe(host);

    let raf = 0;
    let last = 0;
    const start = performance.now();
    const frame = t => {
      raf = requestAnimationFrame(frame);
      if (!visible || document.hidden || t - last < 33) return;      // ~30 fps is plenty for a slow drift
      last = t;
      material.uniforms.uTime.value = (t - start) / 1000;
      renderer.render(scene, camera);
    };
    raf = requestAnimationFrame(frame);
    setReady(true);

    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      mo.disconnect();
      io.disconnect();
      geometry.dispose();
      material.dispose();
      renderer.dispose();
      renderer.forceContextLoss();
      renderer.domElement.remove();
    };
  }, []);

  return <div ref={hostRef} className="backdrop-field" data-ready={ready ? 'y' : 'n'} aria-hidden="true" />;
}
