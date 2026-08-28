import * as THREE from 'three';
import vertexSrc   from './shaders/vertex.glsl?raw';
import fragmentSrc from './shaders/fragment.glsl?raw';


const bg = document.getElementById('hero_bg')
const shapeAttr  = bg?.getAttribute('data-shape') ?? 'square';
const pixelSizeAttr = bg?.getAttribute('data-pixel-size') ?? '4';
const inkAttr = bg?.getAttribute('data-ink') ?? '#FFFFFF';

const SHAPE_MAP: Record<string, number> = {
  square: 0,
  circle: 1,
  triangle: 2,
  diamond: 3,
};

/* ---------- renderer ------------------------------------- */
const canvas  = document.createElement('canvas');
const gl      = canvas.getContext('webgl2')!;
const renderer = new THREE.WebGLRenderer({ canvas, context: gl, antialias: true });
bg?.appendChild(canvas);

/* ---------- uniforms ------------------------------------- */
const MAX_CLICKS = 10;
const uniforms = {
  uResolution : { value: new THREE.Vector2() },
  uTime       : { value: 0 },
  uColor     : { value: new THREE.Color(inkAttr) },
  uClickPos   : { value: Array.from({ length: MAX_CLICKS }, () => new THREE.Vector2(-1, -1)) },
  uClickTimes : { value: new Float32Array(MAX_CLICKS) },
  uShapeType  : { value: SHAPE_MAP[shapeAttr] ?? 0 },
  uPixelSize  : { value: parseFloat(pixelSizeAttr) || 4 },
};

/* ---------- scene / camera / quad ------------------------ */
const scene  = new THREE.Scene();
const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
const material = new THREE.ShaderMaterial({
  vertexShader: vertexSrc,
  fragmentShader: fragmentSrc,
  uniforms,
  glslVersion: THREE.GLSL3,
  transparent: true,
});
scene.add(new THREE.Mesh(new THREE.PlaneGeometry(2, 2), material));

/* ---------- resize helper -------------------------------- */
const resize = () => {
  const w = canvas.clientWidth  || window.innerWidth;
  const h = canvas.clientHeight || window.innerHeight;
  renderer.setSize(w, h, false);
  uniforms.uResolution.value.set(w, h);
};
window.addEventListener('resize', resize);
resize();

/* ---------- click ripple --------------------------------- */
let clickIx = 0;
canvas.addEventListener('pointerdown', e => {
  const rect = canvas.getBoundingClientRect();
  const fx = (e.clientX - rect.left)  * (canvas.width  / rect.width);
  const fy = (rect.height - (e.clientY - rect.top)) * (canvas.height / rect.height);

  uniforms.uClickPos.value[clickIx].set(fx, fy);
  uniforms.uClickTimes.value[clickIx] = uniforms.uTime.value;
  clickIx = (clickIx + 1) % MAX_CLICKS;
});

/* ---------- main loop ------------------------------------ */
const clock = new THREE.Clock();
(function animate() {
  uniforms.uTime.value = clock.getElapsedTime();
  renderer.render(scene, camera);
  requestAnimationFrame(animate);
})();
