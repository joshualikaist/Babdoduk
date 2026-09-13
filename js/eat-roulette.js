(function (root) {
  var EURO = [0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30, 8, 23, 10, 5, 24, 16, 33, 1, 20, 14, 31, 9, 22, 18, 29, 7, 28, 12, 35, 3, 26];
  var RED = {
    1: 1, 3: 1, 5: 1, 7: 1, 9: 1, 12: 1, 14: 1, 16: 1, 18: 1, 19: 1,
    21: 1, 23: 1, 25: 1, 27: 1, 30: 1, 32: 1, 34: 1, 36: 1
  };
  var N = EURO.length;
  var STEP = (Math.PI * 2) / N;
  var FILL = { red: '#c41e3a', black: '#141312', green: '#0f6b3c' };
  var MAX_BALL = 26;
  var MAX_WHEEL = 9;

  function colorOf(n) {
    if (n === 0) return 'green';
    return RED[n] ? 'red' : 'black';
  }

  function wrap(a) {
    var t = Math.PI * 2;
    a = a % t;
    if (a < 0) a += t;
    return a;
  }

  function wrapPi(a) {
    while (a > Math.PI) a -= Math.PI * 2;
    while (a < -Math.PI) a += Math.PI * 2;
    return a;
  }

  function clamp(n, a, b) {
    return Math.max(a, Math.min(b, n));
  }

  function pocketIndex(ballAngle, wheelAngle) {
    var rel = wrap(ballAngle - wheelAngle + Math.PI / 2);
    return Math.floor(rel / STEP) % N;
  }

  function pocketCenter(wheelAngle, idx) {
    return wheelAngle - Math.PI / 2 + (idx + 0.5) * STEP;
  }

  function create(opts) {
    opts = opts || {};
    var host = opts.host;
    if (!host) return null;
    var pockets = opts.pockets || [];
    var onSettle = opts.onSettle || function () {};
    var onStatus = opts.onStatus || function () {};
    var reduced = !!opts.reducedMotion;

    var canvas = document.createElement('canvas');
    canvas.className = 'eat-wheel-canvas';
    canvas.style.touchAction = 'none';
    canvas.setAttribute('role', 'img');
    canvas.setAttribute('aria-label', opts.aria || '룰렛');
    host.innerHTML = '';
    host.appendChild(canvas);
    var ctx = canvas.getContext('2d');

    var dpr = 1;
    var size = 0;
    var cx = 0;
    var cy = 0;
    var R = 0;

    var wheelA = 0;
    var wheelV = 0;
    var ballA = pocketCenter(0, 0);
    var ballV = 0;
    var ballR = 0.72;
    var phase = 'idle';
    var dragging = false;
    var charge = 0;
    var holdMs = 0;
    var lastAng = 0;
    var lastT = 0;
    var samples = [];
    var moved = 0;
    var pointerId = null;
    var raf = 0;
    var lastFrame = 0;
    var settled = false;
    var live = true;
    var deflectHit = [0, 0, 0, 0, 0, 0, 0, 0];

    function trackR() { return 0.905; }
    function pocketR() { return 0.705; }
    function fallW() { return 4.2; }

    function resize() {
      var box = host.getBoundingClientRect();
      var css = Math.max(240, Math.min(box.width || 360, 400));
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      size = Math.round(css * dpr);
      canvas.width = size;
      canvas.height = size;
      canvas.style.width = css + 'px';
      canvas.style.height = css + 'px';
      cx = size / 2;
      cy = size / 2;
      R = size * 0.46;
      draw();
    }

    function localAngle(e) {
      var rect = canvas.getBoundingClientRect();
      var x = e.clientX - rect.left - rect.width / 2;
      var y = e.clientY - rect.top - rect.height / 2;
      return Math.atan2(y, x);
    }

    function applyImpulse(ballKick, wheelKick) {
      if (phase === 'pocket' && Math.abs(wheelV) < 0.2 && Math.abs(ballV) < 0.2) {
        phase = 'track';
        ballR = trackR();
        settled = false;
      }
      if (phase === 'idle') {
        phase = 'track';
        ballR = trackR();
        settled = false;
      }
      if (phase === 'pocket') {
        phase = 'track';
        ballR = trackR();
        settled = false;
      }
      ballV = clamp(ballV + ballKick, -MAX_BALL, MAX_BALL);
      wheelV = clamp(wheelV + wheelKick, -MAX_WHEEL, MAX_WHEEL);
      kick();
    }

    function kick() {
      if (!raf) {
        lastFrame = 0;
        raf = requestAnimationFrame(tick);
      }
    }

    function avgSample() {
      if (!samples.length) return 0;
      var i;
      var sum = 0;
      var w = 0;
      var now = samples[samples.length - 1].t;
      for (i = 0; i < samples.length; i += 1) {
        var age = now - samples[i].t;
        if (age > 90) continue;
        var wt = 1 - age / 90;
        sum += samples[i].w * wt;
        w += wt;
      }
      return w ? sum / w : 0;
    }

    function onDown(e) {
      if (!live) return;
      if (e.pointerType === 'mouse' && e.button !== 0) return;
      if (e && e.preventDefault) e.preventDefault();
      dragging = true;
      charge = 0;
      holdMs = 0;
      moved = 0;
      samples = [];
      lastAng = localAngle(e);
      lastT = e.timeStamp || performance.now();
      pointerId = e.pointerId;
      try { canvas.setPointerCapture(pointerId); } catch (err) {}
      host.classList.add('is-drag');
      kick();
    }

    function onMove(e) {
      if (!dragging) return;
      if (e && e.preventDefault) e.preventDefault();
      var ang = localAngle(e);
      var now = e.timeStamp || performance.now();
      var d = wrapPi(ang - lastAng);
      var dt = Math.max(0.008, (now - lastT) / 1000);
      moved += Math.abs(d);
      lastAng = ang;
      lastT = now;
      samples.push({ w: d / dt, t: now });
      if (samples.length > 12) samples.shift();
      if (moved > 0.04) {
        charge = 0;
        holdMs = 0;
        wheelA += d;
        if (phase === 'idle' || phase === 'pocket') {
          phase = 'track';
          ballR = trackR();
          settled = false;
        }
        ballA += d * 0.12;
      }
      draw();
    }

    function onUp(e) {
      if (!dragging) return;
      dragging = false;
      host.classList.remove('is-drag');
      try { if (pointerId != null) canvas.releasePointerCapture(pointerId); } catch (err) {}
      pointerId = null;
      var flick = avgSample();
      samples = [];
      if (moved > 0.06 && Math.abs(flick) > 0.8) {
        var kickBall = clamp(-flick * 1.15, -MAX_BALL, MAX_BALL);
        var kickWheel = clamp(flick * 0.38, -MAX_WHEEL, MAX_WHEEL);
        if (Math.abs(kickBall) < 4) kickBall = (kickBall < 0 ? -1 : 1) * 4;
        applyImpulse(kickBall, kickWheel);
        onStatus('spin');
      } else if (charge > 1.2) {
        var dir = -1;
        applyImpulse(dir * charge, -dir * charge * 0.32);
        onStatus('spin');
      } else if (moved < 0.05) {
        var tap = 6.4 + Math.min(Math.abs(wheelV) * 0.35, 3);
        var sign = ballV !== 0 ? (ballV > 0 ? 1 : -1) : -1;
        applyImpulse(sign * tap, -sign * 1.35);
        onStatus('spin');
      }
      charge = 0;
      holdMs = 0;
      draw();
    }

    function physics(dt) {
      if (dragging && moved < 0.04) {
        holdMs += dt * 1000;
        if (holdMs > 160) {
          charge = clamp(charge + dt * 14, 0, MAX_BALL);
          onStatus('charge');
        }
      }

      if (phase === 'idle' && !dragging) return;

      var viscB = phase === 'track' ? 0.16 : 0.28;
      var viscW = 0.085;
      var coulB = phase === 'track' ? 0.22 : 0.55;
      var coulW = 0.11;

      wheelV -= wheelV * viscW * dt;
      if (Math.abs(wheelV) > 0.02) wheelV -= Math.sign(wheelV) * coulW * dt;
      else wheelV = 0;

      if (phase !== 'pocket') {
        ballV -= ballV * viscB * dt;
        if (Math.abs(ballV) > 0.02) ballV -= Math.sign(ballV) * coulB * dt;
        else ballV = 0;
      } else {
        ballV = wheelV;
      }

      wheelA += wheelV * dt;
      if (phase !== 'pocket') ballA += ballV * dt;
      else ballA = pocketCenter(wheelA, pocketIndex(ballA, wheelA));

      if (phase === 'track') {
        ballR += (trackR() - ballR) * Math.min(1, dt * 8);
        if (Math.abs(ballV) < fallW()) {
          phase = 'fall';
        }
      } else if (phase === 'fall') {
        ballR += (pocketR() - ballR) * Math.min(1, dt * 2.4);
        var i;
        for (i = 0; i < 8; i += 1) {
          var da = wrapPi(ballA - (i * Math.PI / 4 + Math.PI / 8));
          if (Math.abs(da) < 0.1 && ballR > 0.76 && ballR < 0.9 && deflectHit[i] <= 0) {
            ballV *= 0.52;
            ballV += (Math.random() - 0.5) * 2.4;
            ballR += 0.018;
            deflectHit[i] = 0.18;
          }
          deflectHit[i] -= dt;
        }
        if (ballR <= pocketR() + 0.012) {
          var idx = pocketIndex(ballA, wheelA);
          ballA = pocketCenter(wheelA, idx);
          ballR = pocketR();
          ballV = wheelV;
          phase = 'pocket';
        }
      } else if (phase === 'pocket') {
        ballR += (pocketR() - ballR) * Math.min(1, dt * 10);
        if (!settled && Math.abs(wheelV) < 0.18 && Math.abs(ballV) < 0.18) {
          settled = true;
          wheelV = 0;
          ballV = 0;
          var win = pocketIndex(ballA, wheelA);
          onStatus('land');
          onSettle(pockets[win] || { number: EURO[win], index: win });
        }
      }
    }

    function tick(now) {
      if (!live) return;
      if (!lastFrame) lastFrame = now;
      var dt = Math.min(0.032, (now - lastFrame) / 1000);
      lastFrame = now;
      physics(dt);
      draw();
      var moving = dragging || Math.abs(wheelV) > 0.01 || Math.abs(ballV) > 0.01 || phase === 'fall' || charge > 0;
      if (moving) raf = requestAnimationFrame(tick);
      else raf = 0;
    }

    function draw() {
      if (!ctx) return;
      ctx.clearRect(0, 0, size, size);
      ctx.save();
      ctx.translate(cx, cy);

      var bowl = ctx.createRadialGradient(0, 0, R * 0.2, 0, 0, R * 1.08);
      bowl.addColorStop(0, '#5a3d24');
      bowl.addColorStop(0.55, '#3a2616');
      bowl.addColorStop(1, '#1c140c');
      ctx.beginPath();
      ctx.arc(0, 0, R * 1.08, 0, Math.PI * 2);
      ctx.fillStyle = bowl;
      ctx.fill();

      ctx.beginPath();
      ctx.arc(0, 0, R * 1.02, 0, Math.PI * 2);
      ctx.strokeStyle = '#c6a24a';
      ctx.lineWidth = R * 0.035;
      ctx.stroke();
      ctx.beginPath();
      ctx.arc(0, 0, R * 1.055, 0, Math.PI * 2);
      ctx.strokeStyle = '#8a6a2a';
      ctx.lineWidth = R * 0.012;
      ctx.stroke();

      ctx.save();
      ctx.rotate(wheelA);
      var i;
      for (i = 0; i < N; i += 1) {
        var n = EURO[i];
        var a0 = -Math.PI / 2 + i * STEP;
        ctx.beginPath();
        ctx.moveTo(0, 0);
        ctx.arc(0, 0, R * 0.86, a0, a0 + STEP);
        ctx.closePath();
        ctx.fillStyle = FILL[colorOf(n)];
        ctx.fill();
        ctx.strokeStyle = 'rgba(212, 175, 55, 0.35)';
        ctx.lineWidth = 1;
        ctx.stroke();

        var mid = a0 + STEP / 2;
        ctx.save();
        ctx.rotate(mid + Math.PI / 2);
        ctx.fillStyle = '#f7f1e4';
        ctx.font = '700 ' + Math.max(9, R * 0.055) + 'px "Noto Sans KR", sans-serif';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(String(n), 0, -R * 0.755);
        ctx.restore();
      }

      ctx.beginPath();
      ctx.arc(0, 0, R * 0.58, 0, Math.PI * 2);
      ctx.fillStyle = '#2a1c10';
      ctx.fill();
      ctx.beginPath();
      ctx.arc(0, 0, R * 0.58, 0, Math.PI * 2);
      ctx.strokeStyle = '#c6a24a';
      ctx.lineWidth = R * 0.018;
      ctx.stroke();

      var hub = ctx.createRadialGradient(-R * 0.06, -R * 0.06, R * 0.02, 0, 0, R * 0.28);
      hub.addColorStop(0, '#f0d789');
      hub.addColorStop(0.45, '#c6a24a');
      hub.addColorStop(1, '#6e531c');
      ctx.beginPath();
      ctx.arc(0, 0, R * 0.26, 0, Math.PI * 2);
      ctx.fillStyle = hub;
      ctx.fill();
      ctx.strokeStyle = '#f3e2a8';
      ctx.lineWidth = 1.5;
      ctx.stroke();

      ctx.save();
      ctx.rotate(Math.PI / 4);
      ctx.fillStyle = '#f7f4ee';
      var d;
      for (d = 0; d < 4; d += 1) {
        ctx.rotate(Math.PI / 2);
        ctx.beginPath();
        ctx.moveTo(0, -R * 0.2);
        ctx.lineTo(R * 0.035, -R * 0.08);
        ctx.lineTo(-R * 0.035, -R * 0.08);
        ctx.closePath();
        ctx.fill();
      }
      ctx.restore();
      ctx.restore();

      ctx.beginPath();
      ctx.arc(0, 0, R * 0.93, 0, Math.PI * 2);
      ctx.strokeStyle = 'rgba(20, 16, 10, 0.55)';
      ctx.lineWidth = R * 0.045;
      ctx.stroke();

      for (i = 0; i < 8; i += 1) {
        var ang = i * Math.PI / 4 + Math.PI / 8;
        ctx.save();
        ctx.rotate(ang);
        ctx.translate(0, -R * 0.84);
        ctx.fillStyle = '#d7c389';
        ctx.beginPath();
        ctx.moveTo(0, -R * 0.04);
        ctx.lineTo(R * 0.028, 0);
        ctx.lineTo(0, R * 0.04);
        ctx.lineTo(-R * 0.028, 0);
        ctx.closePath();
        ctx.fill();
        ctx.restore();
      }

      if (charge > 0.4) {
        ctx.beginPath();
        ctx.arc(0, 0, R * 1.02, -Math.PI / 2, -Math.PI / 2 + (charge / MAX_BALL) * Math.PI * 2);
        ctx.strokeStyle = '#f45e45';
        ctx.lineWidth = R * 0.028;
        ctx.stroke();
      }

      var br = ballR * R;
      var bx = Math.cos(ballA) * br;
      var by = Math.sin(ballA) * br;
      ctx.beginPath();
      ctx.arc(bx + R * 0.012, by + R * 0.016, R * 0.038, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(0, 0, 0, 0.28)';
      ctx.fill();
      var shine = ctx.createRadialGradient(bx - R * 0.012, by - R * 0.014, R * 0.004, bx, by, R * 0.04);
      shine.addColorStop(0, '#fffdf8');
      shine.addColorStop(0.45, '#e8e2d4');
      shine.addColorStop(1, '#9a9488');
      ctx.beginPath();
      ctx.arc(bx, by, R * 0.036, 0, Math.PI * 2);
      ctx.fillStyle = shine;
      ctx.fill();

      ctx.restore();
    }

    function onLost() {
      if (dragging) onUp({});
    }

    canvas.addEventListener('pointerdown', onDown);
    canvas.addEventListener('pointermove', onMove);
    canvas.addEventListener('pointerup', onUp);
    canvas.addEventListener('pointercancel', onUp);
    canvas.addEventListener('lostpointercapture', onLost);
    window.addEventListener('resize', resize);
    resize();

    return {
      impulse: function (strength) {
        var s = clamp(strength == null ? 8 : strength, 3, MAX_BALL);
        if (reduced) {
          var idx = Math.floor(Math.random() * N);
          ballA = pocketCenter(wheelA, idx);
          ballR = pocketR();
          phase = 'pocket';
          wheelV = 0;
          ballV = 0;
          settled = true;
          draw();
          onSettle(pockets[idx] || { number: EURO[idx], index: idx });
          return;
        }
        applyImpulse(-s, s * 0.34);
        onStatus('spin');
      },
      destroy: function () {
        live = false;
        if (raf) cancelAnimationFrame(raf);
        raf = 0;
        canvas.removeEventListener('pointerdown', onDown);
        canvas.removeEventListener('pointermove', onMove);
        canvas.removeEventListener('pointerup', onUp);
        canvas.removeEventListener('pointercancel', onUp);
        canvas.removeEventListener('lostpointercapture', onLost);
        window.removeEventListener('resize', resize);
        if (canvas.parentNode) canvas.parentNode.removeChild(canvas);
      }
    };
  }

  root.BabdodukRoulette = {
    create: create,
    EURO: EURO,
    colorOf: colorOf
  };
})(window);
