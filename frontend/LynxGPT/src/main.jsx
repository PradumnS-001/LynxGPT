import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'

function setDynamicAccent() {
  const accents = [
    { name: 'deep-violet', hex: '#8A2BE2' },
    { name: 'hot-pink', hex: '#FF46A2' },
    { name: 'sky-blue', hex: '#4E9FE5' },
    { name: 'neon-emerald', hex: '#50FFB1' },
    { name: 'daisy-yellow', hex: '#F8D675' },
    { name: 'sunset-orange', hex: '#FF8C00' },
    { name: 'crimson-red', hex: '#FF0033' }
  ];

  // pick exactly one accent per page load
  const choice_num = Math.floor(Math.random() * accents.length);
  const choice = accents[choice_num];
  let choice_prev = choice_num - 1;
  let choice_next = choice_num + 1;
  if (choice_num === 0) {
    choice_prev = { name: 'sky-blue', hex: '#3214e0ff' };
    choice_next = accents[choice_next];
  }
  if (choice_num === accents.length - 1) {
    choice_prev = accents[choice_prev];
    choice_next = { name: 'daisy-yellow', hex: '#F8D675' };
  }
  if (choice_num != 0 && choice_num != accents.length - 1) {
    choice_prev = accents[choice_prev];
    choice_next = accents[choice_next];
  }
  
  // helper to darken a hex color by factor (0-1)
  function darken(hex, factor = 0.5) {
    const c = hex.replace('#', '');
    const r = parseInt(c.substring(0, 2), 16);
    const g = parseInt(c.substring(2, 4), 16);
    const b = parseInt(c.substring(4, 6), 16);
    const nr = Math.max(0, Math.floor(r * factor));
    const ng = Math.max(0, Math.floor(g * factor));
    const nb = Math.max(0, Math.floor(b * factor));
    return `#${nr.toString(16).padStart(2, '0')}${ng.toString(16).padStart(2, '0')}${nb.toString(16).padStart(2, '0')}`;
  }

  const vibrant = choice.hex;
  const vibrant_prev = choice_prev.hex;
  const vibrant_next = choice_next.hex;
  const darkest = darken(vibrant, 0.28); // darkest shade for background

  function hexToRgb(hex) {
    const c = hex.replace('#', '');
    const r = parseInt(c.substring(0, 2), 16);
    const g = parseInt(c.substring(2, 4), 16);
    const b = parseInt(c.substring(4, 6), 16);
    return `${r}, ${g}, ${b}`;
  }

  const root = document.documentElement;
  root.style.setProperty('--accent-name', choice.name);
  root.style.setProperty('--accent-vibrant', vibrant);
  root.style.setProperty('--accent-vibrant-prev', vibrant_prev);
  root.style.setProperty('--accent-vibrant-next', vibrant_next);
  root.style.setProperty('--accent-dark', darkest);
  root.style.setProperty('--accent-border', `rgba(${hexToRgb(vibrant)}, 0.2)`);
  root.style.setProperty('--accent-glow', vibrant);
  root.style.setProperty('--accent-rgb', hexToRgb(vibrant));

  // inject two animated orb elements for lighting (if not already present)
  if (!document.querySelector('.radial-accent-blob-1')) {
    const b1 = document.createElement('div');
    b1.className = 'radial-accent-blob-1';
    document.body.appendChild(b1);
  }
  if (!document.querySelector('.radial-accent-blob-2')) {
    const b2 = document.createElement('div');
    b2.className = 'radial-accent-blob-2';
    document.body.appendChild(b2);
  }

  // inject 7 ethereal orbs at 7 fixed positions with randomized radii (scale 0.9-1.1)
  if (!document.querySelector('.ethereal-orb-1')) {
    const positions = [
      { left: '25%', top: '8%' },    // Top Left
      { left: '60%', top: '12%' },    // Top Center (High)
      { left: '85%', top: '25%' },    // Top Right (Lower than Top Left)
      { left: '10%', top: '55%' },    // Mid Left
      { left: '45%', top: '50%' },    // Center (Slightly offset)
      { left: '80%', top: '75%' },    // Bottom Right
      { left: '25%', top: '85%' }     // Bottom Left (Low)
    ];

    for (let i = 1; i <= 7; i++) {
      const orb = document.createElement('div');
      orb.className = `ethereal-orb ethereal-orb-${i}`;
      // apply the fixed position from the list
      const pos = positions[i - 1];
      Object.entries(pos).forEach(([k, v]) => { orb.style[k] = v; });
      // randomize radius (scale) between 0.75 and 1.0
      const randomScale = 0.6 + Math.random() * 0.6;
      orb.style.transform = `scale(${randomScale})`;
      document.body.appendChild(orb);
    }
  }
}

setDynamicAccent();

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
