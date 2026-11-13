/* The home page's campus map (docs/CAMPUS_MAP.md, owner 2026-11-04): the clay miniature where the
   photo collage was, with a pin on each event of the day the calendar shows (babdoduk:day from
   js/home-calendar.js). Wider than 720 px it sits beside the copy and wakes when it is on screen;
   on phones only the "지도 보기" button shows, and the map opens in a full-screen dialog.
   "일정에서 보기" on a pin's card asks the calendar to open that event (babdoduk:show).
   js/campus-map.js and the Three.js files under it (about 2.4 MB) are imported only when the map
   wakes, so a phone that never opens the map does not download them. Until then the poster shows. */

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
  loading = import('./campus-map.js?v=665f0f69e7').then(({ mount }) => {
    map = mount(stage, {
      lang, t,
      onOpen(id) {
        if (dialog && dialog.open) dialog.close();
        document.dispatchEvent(new CustomEvent('babdoduk:show', { detail: { id } }));
      },
      onFull: dialog && typeof dialog.showModal === 'function' ? openDialog : null,
    });
    // Days the calendar announced while the module loaded are in babdodukCalendarDay.
    if (window.babdodukCalendarDay) map.show(window.babdodukCalendarDay);
  }).catch(() => { loading = null; });   // the poster stays; the next wake tries again
}

if (stage) {
  document.addEventListener('babdoduk:day', (e) => { if (map) map.show(e.detail); });
  document.addEventListener('babdoduk-lang', () => { if (map) map.relabel(); });

  // Beside the copy: wake the map the first time it is on screen.
  const io = new IntersectionObserver((entries) => {
    if (!phone.matches && entries.some((en) => en.isIntersecting)) {
      io.disconnect();
      ensure();
    }
  });
  io.observe(section);

  // Phones: the button opens the map in a dialog; wider screens open the same dialog with 크게 보기.
  // Closing puts the map back.
  if (openButton && dialog && typeof dialog.showModal === 'function') {
    openButton.hidden = false;
    openButton.addEventListener('click', openDialog);
    dialog.addEventListener('close', () => {
      section.appendChild(frame);
      // "일정에서 보기" has already moved focus to the calendar; otherwise back to what opened it.
      const now = document.activeElement;
      const back = phone.matches ? openButton : stage.querySelector('[data-map-act="full"]');
      if ((!now || now === document.body || dialog.contains(now)) && back) {
        back.hidden = false;            // the map hides 크게 보기 while it is full screen
        back.focus();
      }
    });
    dialog.querySelector('.home-map-dialog-close').addEventListener('click', () => dialog.close());
  }
}
