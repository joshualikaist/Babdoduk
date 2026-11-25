const section = document.getElementById('homeMap');
const frame = document.getElementById('homeMapFrame');
const stage = frame && frame.querySelector('.home-map-stage');
const openButton = document.getElementById('homeMapOpen');
const dialog = document.getElementById('homeMapDialog');
const phone = window.matchMedia('(max-width: 720px)');

function lang() { return window.babdodukGetLang ? window.babdodukGetLang() : 'ko'; }
function t(key, fallback) {
  const pack = window.BABDODUK_STR && window.BABDODUK_STR[lang()];
  return pack && pack[key] != null ? pack[key] : fallback;
}

let map = null;
let loading = null;
function openDialog() {
  dialog.querySelector('.home-map-dialog-body').appendChild(frame);
  dialog.showModal();
  ensure();
}
function ensure() {
  if (map || loading || !stage) return;
  loading = import('./campus-map.js?v=fbebb9c687').then(({ mount }) => {
    map = mount(stage, {
      lang, t,
      onOpen(id) {
        if (dialog && dialog.open) dialog.close();
        document.dispatchEvent(new CustomEvent('babdoduk:show', { detail: { id } }));
      },
      onFull: dialog && typeof dialog.showModal === 'function' ? openDialog : null,
    });
    if (window.babdodukCalendarDay) map.show(window.babdodukCalendarDay);
  }).catch(() => { loading = null; });
}

if (stage) {
  document.addEventListener('babdoduk:day', (e) => { if (map) map.show(e.detail); });
  document.addEventListener('babdoduk-lang', () => { if (map) map.relabel(); });

  const io = new IntersectionObserver((entries) => {
    if (!phone.matches && entries.some((en) => en.isIntersecting)) {
      io.disconnect();
      ensure();
    }
  });
  io.observe(section);

  if (openButton && dialog && typeof dialog.showModal === 'function') {
    openButton.hidden = false;
    openButton.addEventListener('click', openDialog);
    dialog.addEventListener('close', () => {
      section.appendChild(frame);
      const now = document.activeElement;
      const back = phone.matches ? openButton : stage.querySelector('[data-map-act="full"]');
      if ((!now || now === document.body || dialog.contains(now)) && back) {
        back.hidden = false;
        back.focus();
      }
    });
    dialog.querySelector('.home-map-dialog-close').addEventListener('click', () => dialog.close());
  }
}
