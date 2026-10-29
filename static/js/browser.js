/* Browser adapters only: dialog, clipboard, random seed and HTMX feedback.
   Python owns contact HTML and authoritative navigation; HTMX owns requests. */
(() => {
  'use strict';
  const $ = selector => document.querySelector(selector);
  const pending = new Set();
  let toastTimer;
  function toast(text) {
    const target = $('#toast');
    target.textContent = text;
    target.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => target.classList.remove('show'), 2400);
  }
  function failure() {
    const target = $('#error');
    if (target) target.textContent = 'The request could not be completed. Your last batch is preserved. Please try again.';
  }
  document.addEventListener('click', async event => {
    if (event.target.closest('#shuffle')) {
      $('#seed').value = String(crypto.getRandomValues(new Uint32Array(1))[0]);
      $('#generator').requestSubmit();
    }
    if (event.target.closest('.close-dialog')) $('#detail').close();
    const button = event.target.closest('[data-copy]');
    if (button) {
      try {
        const data = JSON.parse(document.getElementById(button.dataset.copy).textContent);
        await navigator.clipboard.writeText(JSON.stringify(data, null, 2));
        toast('Contact copied as JSON');
      } catch { toast('Clipboard unavailable. Use Export batch to download.'); }
    }
    const disabled = event.target.closest('[aria-disabled="true"]');
    if (disabled) event.preventDefault();
    document.querySelectorAll('.export-menu[open]').forEach(menu => {
      if (!menu.contains(event.target)) menu.open = false;
    });
  });
  const dialog = $('#detail');
  dialog?.addEventListener('click', event => {
    if (event.target !== dialog) return;
    const bounds = dialog.getBoundingClientRect();
    if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) dialog.close();
  });
  // HTMX 4 uses hyphenated events with metaCharacter="-".
  document.addEventListener('htmx-before-request', event => {
    pending.add(event.detail.ctx);
    if ($('#error')) $('#error').textContent = '';
    document.body.classList.add('loading');
    if (event.target.closest?.('#generator')) $('#generate')?.setAttribute('aria-busy', 'true');
  });
  document.addEventListener('htmx-finally-request', event => {
    pending.delete(event.detail.ctx);
    document.body.classList.toggle('loading', pending.size > 0);
    if (!pending.size) $('#generate')?.removeAttribute('aria-busy');
  });
  document.addEventListener('htmx-after-swap', event => {
    if (event.detail?.ctx?.target?.id === 'detail-content' || event.target.id === 'detail-content') {
      if (!dialog.open) dialog.showModal();
    }
  });
  document.addEventListener('htmx-error', event => {
    // Replaced requests are intentionally aborted, not reported as failures.
    if (event.detail.error?.name !== 'AbortError') failure();
  });
})();
