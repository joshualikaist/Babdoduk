(function (root) {
  var COUNT = 12;
  var STEP = 360 / COUNT;
  var ITEM_H = 54;
  var RADIUS = ITEM_H / (2 * Math.tan(Math.PI / COUNT));
  var CUISINE = {
    korean: '한식',
    chinese: '중식',
    japanese: '일식',
    western: '양식',
    'southeast-asian': '동남아',
    indian: '인도',
    'middle-eastern': '중동',
    fusion: '퓨전',
    snack: '분식',
    dessert: '디저트'
  };

  function clamp(n, a, b) {
    return Math.max(a, Math.min(b, n));
  }

  function cuisineLabel(food) {
    if (!food) return '한식';
    return CUISINE[food.cuisine] || CUISINE[food.cuisineGroup] || '한식';
  }

  function dishLabel(food) {
    if (!food) return '';
    return food.nameKo || food.nameEn || '';
  }

  function traitLabel(food) {
    if (!food) return '집밥';
    var bits = [];
    var flavor = food.flavor || {};
    var texture = food.texture || {};
    if (flavor.spicy >= 4) bits.push('매콤');
    if ((food.satiety || 0) >= 4) bits.push('든든');
    else if ((food.satiety || 0) <= 2) bits.push('가볍게');
    if ((food.healthiness || 0) >= 4) bits.push('담백');
    if (flavor.sweet >= 4) bits.push('달콤');
    if ((texture.soupy || 0) >= 4) bits.push('국물');
    if (!bits.length) bits.push('집밥');
    return bits.slice(0, 2).join(' · ');
  }

  function labelsOf(food) {
    return [cuisineLabel(food), dishLabel(food), traitLabel(food)];
  }

  function uniqueFill(target, pool, take) {
    var out = [];
    var seen = {};
    seen[target] = true;
    var i;
    for (i = 0; i < pool.length && out.length < take; i += 1) {
      var val = pool[i];
      if (!val || seen[val]) continue;
      seen[val] = true;
      out.push(val);
    }
    while (out.length < take) out.push(target);
    return out;
  }

  function shuffle(list) {
    var arr = list.slice();
    var i;
    for (i = arr.length - 1; i > 0; i -= 1) {
      var j = Math.floor(Math.random() * (i + 1));
      var tmp = arr[i];
      arr[i] = arr[j];
      arr[j] = tmp;
    }
    return arr;
  }

  function spinEase(t) {
    if (t <= 0) return 0;
    if (t >= 1) return 1;
    if (t < 0.14) {
      var u = t / 0.14;
      return 0.1 * u * u * u;
    }
    if (t < 0.44) return 0.1 + (t - 0.14) / 0.3 * 0.52;
    if (t < 0.78) {
      var d = (t - 0.44) / 0.34;
      return 0.62 + 0.33 * (1 - Math.pow(1 - d, 2));
    }
    if (t < 0.9) {
      var o = (t - 0.78) / 0.12;
      return 0.95 + 0.07 * Math.sin(o * Math.PI);
    }
    var s = (t - 0.9) / 0.1;
    return 1.02 - 0.02 * s - 0.018 * Math.sin(s * Math.PI);
  }

  function create(opts) {
    opts = opts || {};
    var host = opts.host;
    if (!host) return null;
    var reduced = !!opts.reducedMotion;
    var onSettle = opts.onSettle || function () {};
    var onStatus = opts.onStatus || function () {};
    var live = true;
    var spinning = false;
    var raf = 0;
    var resultFood = null;
    var jobs = [];

    host.innerHTML = '';
    host.classList.add('eat-slot-host');
    var machine = document.createElement('div');
    machine.className = 'eat-slot';
    machine.setAttribute('role', 'img');
    machine.setAttribute('aria-label', opts.aria || '오늘 메뉴를 뽑는 슬롯');
    machine.innerHTML =
      '<div class="eat-slot-top" aria-hidden="true"></div>' +
      '<div class="eat-slot-face">' +
        '<div class="eat-slot-window">' +
          '<div class="eat-reel" data-reel="0"><div class="eat-reel-ring"></div></div>' +
          '<div class="eat-reel" data-reel="1"><div class="eat-reel-ring"></div></div>' +
          '<div class="eat-reel" data-reel="2"><div class="eat-reel-ring"></div></div>' +
          '<div class="eat-payline" aria-hidden="true"><span></span><b></b><span></span></div>' +
        '</div>' +
      '</div>' +
      '<div class="eat-slot-bottom" aria-hidden="true"></div>';
    host.appendChild(machine);

    var rings = [
      machine.querySelector('[data-reel="0"] .eat-reel-ring'),
      machine.querySelector('[data-reel="1"] .eat-reel-ring'),
      machine.querySelector('[data-reel="2"] .eat-reel-ring')
    ];
    var angles = [0, 0, 0];

    function setAngle(idx, deg, blurring) {
      angles[idx] = deg;
      rings[idx].style.transform = 'rotateX(' + deg + 'deg)';
      rings[idx].parentNode.classList.toggle('is-fast', !!blurring);
    }

    function paintRing(idx, symbols) {
      var html = '';
      var i;
      for (i = 0; i < COUNT; i += 1) {
        html += '<span class="eat-symbol" style="transform:rotateX(' + (i * STEP) + 'deg) translateZ(' + RADIUS.toFixed(2) + 'px)"><b>' +
          String(symbols[i] || '').replace(/[&<>]/g, function (ch) {
            return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' })[ch];
          }) + '</b></span>';
      }
      rings[idx].innerHTML = html;
    }

    function poolFor(kind, foods, target) {
      var values = [];
      (foods || []).forEach(function (food) {
        values.push(labelsOf(food)[kind]);
      });
      return uniqueFill(target, shuffle(values), COUNT - 1);
    }

    function layout(food, foods, slot) {
      slot = slot == null ? 5 : slot;
      var labels = labelsOf(food);
      var i;
      for (i = 0; i < 3; i += 1) {
        var fillers = poolFor(i, foods, labels[i]);
        var symbols = fillers.slice();
        symbols.splice(slot, 0, labels[i]);
        paintRing(i, symbols.slice(0, COUNT));
        setAngle(i, -slot * STEP, false);
      }
    }

    function nudge(kind) {
      machine.classList.remove('is-hit-0', 'is-hit-1', 'is-hit-2');
      machine.classList.add('is-hit-' + kind);
      window.setTimeout(function () { machine.classList.remove('is-hit-' + kind); }, 240);
    }

    function tick(now) {
      if (!live) return;
      var allDone = true;
      var i;
      for (i = 0; i < jobs.length; i += 1) {
        var job = jobs[i];
        if (job.done) continue;
        var t = clamp((now - job.start) / job.duration, 0, 1);
        if (now < job.start) {
          allDone = false;
          continue;
        }
        var p = spinEase(t);
        setAngle(job.idx, job.from + (job.to - job.from) * p, t > 0.08 && t < 0.74);
        if (t >= 1) {
          setAngle(job.idx, job.to, false);
          job.done = true;
          nudge(job.idx);
          if (job.idx === 2) machine.classList.add('is-payline');
        } else allDone = false;
      }
      if (allDone) {
        raf = 0;
        machine.classList.remove('is-spinning');
        spinning = false;
        onStatus('land');
        onSettle({ food: resultFood, labels: labelsOf(resultFood) });
        return;
      }
      raf = requestAnimationFrame(tick);
    }

    function spinTo(food, foods) {
      if (!live || spinning || !food) return Promise.resolve(food);
      spinning = true;
      resultFood = food;
      machine.classList.remove('is-payline');
      machine.classList.add('is-spinning');
      var slot = 5;
      var labels = labelsOf(food);
      var turns = reduced ? [0.2, 0.28, 0.36] : [5.4, 7.0, 8.7];
      var durations = reduced ? [320, 380, 460] : [1680, 1980, 2260];
      var start = performance.now() + 90;
      var i;
      jobs = [];
      for (i = 0; i < 3; i += 1) {
        var fillers = poolFor(i, foods, labels[i]);
        var symbols = fillers.slice();
        symbols.splice(slot, 0, labels[i]);
        paintRing(i, symbols.slice(0, COUNT));
        var from = reduced ? 0 : 3.6;
        var to = -(turns[i] * 360 + slot * STEP);
        setAngle(i, from, false);
        jobs.push({
          idx: i,
          from: from,
          to: to,
          duration: durations[i],
          start: start + i * (reduced ? 30 : 80),
          done: false
        });
      }
      onStatus('spin');
      if (raf) cancelAnimationFrame(raf);
      raf = requestAnimationFrame(tick);
      return Promise.resolve(food);
    }

    layout((opts.foods && opts.foods[0]) || { nameKo: '제육볶음', cuisine: 'korean', satiety: 4, flavor: { spicy: 4 } }, opts.foods || [], 4);

    return {
      spinning: function () { return spinning; },
      preview: function (foods) {
        if (!spinning) layout((foods && foods[0]) || { nameKo: '제육볶음', cuisine: 'korean' }, foods || [], 4);
      },
      spin: function (food, foods) { return spinTo(food, foods || []); },
      destroy: function () {
        live = false;
        spinning = false;
        if (raf) cancelAnimationFrame(raf);
        raf = 0;
        host.classList.remove('eat-slot-host');
        host.innerHTML = '';
      }
    };
  }

  root.BabdodukSlot = {
    create: create,
    labelsOf: labelsOf,
    cuisineLabel: cuisineLabel,
    traitLabel: traitLabel
  };
})(window);
