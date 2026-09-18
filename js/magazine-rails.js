(function () {
  function reduced() {
    return window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  }

  function bindRail(box) {
    if (!box || box.getAttribute('data-rail-bound')) return;
    box.setAttribute('data-rail-bound', '1');
    var pausedUntil = 0;
    var timer = 0;

    function pause(ms) {
      pausedUntil = Date.now() + (ms || 10000);
    }

    function step() {
      if (reduced()) return;
      if (Date.now() < pausedUntil) return;
      if (box.matches(':hover') || box.contains(document.activeElement)) return;
      var card = box.querySelector('.mg-story');
      if (!card) return;
      var next = card.getBoundingClientRect().width + 14;
      if (box.scrollLeft + box.clientWidth >= box.scrollWidth - 8) {
        box.scrollTo({ left: 0, behavior: 'smooth' });
      } else {
        box.scrollBy({ left: next, behavior: 'smooth' });
      }
    }

    ['pointerdown', 'wheel', 'touchstart', 'focusin', 'mouseenter'].forEach(function (ev) {
      box.addEventListener(ev, function () { pause(10000); }, { passive: true });
    });
    timer = window.setInterval(step, 5200);
    box.addEventListener('remove', function () { window.clearInterval(timer); });
  }

  window.BabdodukMagazineRails = {
    bind: function () {
      document.querySelectorAll('.mg-lane--trend .mg-lane-items').forEach(bindRail);
    }
  };
})();
