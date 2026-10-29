/* Browser preference only. Runs before CSS to avoid a theme flash. */
(() => {
  'use strict';
  const key = 'nominal-theme';
  let theme = 'dark';
  try { theme = localStorage.getItem(key) || 'dark'; } catch {}
  const apply = value => {
    document.documentElement.dataset.theme = value;
    document.documentElement.style.colorScheme = value;
    const label = document.querySelector('#theme-label');
    const toggle = document.querySelector('#theme-toggle');
    const next = value === 'dark' ? 'light' : 'dark';
    if (label) label.textContent = `${next[0].toUpperCase()}${next.slice(1)} mode`;
    if (toggle) toggle.setAttribute('aria-label', `Switch to ${next} mode`);
    document.dispatchEvent(new CustomEvent('nominal:theme'));
  };
  apply(theme === 'light' ? 'light' : 'dark');
  document.addEventListener('DOMContentLoaded', () => {
    apply(document.documentElement.dataset.theme);
    document.querySelector('#theme-toggle')?.addEventListener('click', () => {
      const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
      try { localStorage.setItem(key, next); } catch {}
      apply(next);
    });
  });
})();
