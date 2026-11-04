/* The home page's campus map (docs/CAMPUS_MAP.md, owner 2026-11-04): the clay miniature where the
   photo collage was, with a pin on each event of the day the calendar shows (babdoduk:day from
   js/home-calendar.js). Wider than 720 px it sits beside the copy and wakes when it is on screen;
   on phones only the "지도 보기" button shows, and the map opens in a full-screen dialog.
   "일정에서 보기" on a pin's card asks the calendar to open that event (babdoduk:show). */
import { mount } from './campus-map.js';

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
function ensure() {
  if (map || !stage) return map;
  map = mount(stage, {
    lang, t,
    onOpen(id) {
      if (dialog && dialog.open) dialog.close();
      document.dispatchEvent(new CustomEvent('babdoduk:show', { detail: { id } }));
    },
  });
  if (window.babdodukCalendarDay) map.show(window.babdodukCalendarDay);
  return map;
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

  // Phones: the button opens the map in a dialog; closing puts it back.
  if (openButton && dialog && typeof dialog.showModal === 'function') {
    openButton.hidden = false;
    openButton.addEventListener('click', () => {
      dialog.querySelector('.home-map-dialog-body').appendChild(frame);
      dialog.showModal();
      ensure();
    });
    dialog.addEventListener('close', () => {
      section.appendChild(frame);
      // "일정에서 보기" has already moved focus to the calendar; otherwise back to the button.
      const now = document.activeElement;
      if (!now || now === document.body || dialog.contains(now)) openButton.focus();
    });
    dialog.querySelector('.home-map-dialog-close').addEventListener('click', () => dialog.close());
  }
}
