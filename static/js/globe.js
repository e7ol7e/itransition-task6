/* Canvas projection and gestures only. Coordinates always come from SQL. */
(() => {
  'use strict';
  let cleanup = () => {};
  function mount() {
    const canvas = document.querySelector('#globe');
    if (!canvas || canvas.dataset.mounted) return;
    cleanup();
    canvas.dataset.mounted = 'true';
    const data = JSON.parse(document.querySelector('#batch-data').textContent);
    const ctx = canvas.getContext('2d');
    const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
    let width, height, radius, cx, cy, yaw = -.4, pitch = .18, dragging = false;
    let lastX = 0, lastY = 0, frame, last = 0, dead = false;
    const colors = () => {
      const style = getComputedStyle(canvas);
      return {surface: style.getPropertyValue('--globe-fill').trim(), grid: style.getPropertyValue('--globe-grid').trim(), point: style.getPropertyValue('--accent').trim()};
    };
    function project(lat, lon) {
      const la = lat * Math.PI / 180, lo = lon * Math.PI / 180 + yaw;
      const x = Math.cos(la) * Math.sin(lo), y = Math.sin(la), z = Math.cos(la) * Math.cos(lo);
      return [cx + radius * x, cy - radius * (y * Math.cos(pitch) - z * Math.sin(pitch)), y * Math.sin(pitch) + z * Math.cos(pitch)];
    }
    function path(points) {
      ctx.beginPath();
      let visible = false;
      points.forEach(([lat, lon]) => {
        const [x, y, z] = project(lat, lon);
        if (z < 0) { visible = false; return; }
        if (visible) ctx.lineTo(x, y); else ctx.moveTo(x, y);
        visible = true;
      });
      ctx.stroke();
    }
    const latitudes = Array.from({length: 11}, (_, i) => Array.from({length: 181}, (_, j) => [i * 15 - 75, j * 2 - 180]));
    const longitudes = Array.from({length: 24}, (_, i) => Array.from({length: 91}, (_, j) => [j * 2 - 90, i * 15 - 180]));
    function draw() {
      if (!width) return;
      const palette = colors();
      ctx.clearRect(0, 0, width, height);
      ctx.fillStyle = palette.surface;
      ctx.beginPath(); ctx.arc(cx, cy, radius, 0, 2 * Math.PI); ctx.fill();
      ctx.strokeStyle = palette.grid; ctx.lineWidth = .65;
      latitudes.forEach(path); longitudes.forEach(path);
      ctx.beginPath(); ctx.arc(cx, cy, radius, 0, 2 * Math.PI); ctx.stroke();
      data.contacts.forEach(contact => {
        const [x, y, z] = project(contact.coordinates.latitude, contact.coordinates.longitude);
        if (z < 0) return;
        ctx.fillStyle = palette.point;
        ctx.globalAlpha = .15; ctx.beginPath(); ctx.arc(x, y, 8, 0, 2 * Math.PI); ctx.fill();
        ctx.globalAlpha = 1; ctx.beginPath(); ctx.arc(x, y, 2.7, 0, 2 * Math.PI); ctx.fill();
      });
    }
    function resize() {
      const bounds = canvas.getBoundingClientRect(), dpr = Math.min(devicePixelRatio, 2);
      width = bounds.width; height = bounds.height;
      canvas.width = width * dpr; canvas.height = height * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      radius = Math.min(width * .41, height * .43); cx = width / 2; cy = height / 2;
      draw();
    }
    function animate(time) {
      if (dead) return;
      if (time - last > 45 && !document.hidden) {
        if (!dragging && !reduced) yaw += .002;
        draw(); last = time;
      }
      frame = requestAnimationFrame(animate);
    }
    canvas.onpointerdown = event => { dragging = true; lastX = event.clientX; lastY = event.clientY; canvas.setPointerCapture(event.pointerId); };
    canvas.onpointermove = event => {
      if (!dragging) return;
      yaw += (event.clientX - lastX) * .012;
      pitch = Math.max(-1.2, Math.min(1.2, pitch + (event.clientY - lastY) * .009));
      lastX = event.clientX; lastY = event.clientY; draw();
    };
    canvas.onpointerup = canvas.onpointercancel = () => { dragging = false; };
    const observer = new ResizeObserver(resize);
    observer.observe(canvas);
    document.addEventListener('nominal:theme', draw);
    resize(); frame = requestAnimationFrame(animate);
    cleanup = () => { dead = true; cancelAnimationFrame(frame); observer.disconnect(); document.removeEventListener('nominal:theme', draw); };
  }
  mount();
  document.addEventListener('htmx-after-swap', mount);
})();
