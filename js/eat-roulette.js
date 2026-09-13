(function (root) {
  var EURO = [0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30, 8, 23, 10, 5, 24, 16, 33, 1, 20, 14, 31, 9, 22, 18, 29, 7, 28, 12, 35, 3, 26];
  var RED = {
    1: 1, 3: 1, 5: 1, 7: 1, 9: 1, 12: 1, 14: 1, 16: 1, 18: 1, 19: 1,
    21: 1, 23: 1, 25: 1, 27: 1, 30: 1, 32: 1, 34: 1, 36: 1
  };
  var N = EURO.length;
  var STEP = (Math.PI * 2) / N;
  var FILL = { red: '#c41e3a', black: '#161412', green: '#0f6b3c' };
  var FILL_SIDE = { red: '#8a1528', black: '#0a0908', green: '#0a4a2a' };
  var MAX_BALL = 26;
  var MAX_WHEEL = 9;
  var CAM_Y = 2.24;
  var CAM_Z = -2.72;
  var LOOK_Y = 0.08;
  var FOV = 1.42;
  var CAM_TH = Math.atan2(LOOK_Y - CAM_Y, -CAM_Z);
  var CCOS = Math.cos(CAM_TH);
  var CSIN = Math.sin(CAM_TH);

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

    var cx = 0;
    var cy = 0;
    var SCALE = 0;
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

    function project(x, y, z) {
      var dy = y - CAM_Y;
      var dz = z - CAM_Z;
      var y2 = dy * CCOS - dz * CSIN;
      var z2 = dy * CSIN + dz * CCOS;
      var s = FOV / Math.max(0.35, z2);
      return {
        x: cx + x * s * SCALE,
        y: cy - y2 * s * SCALE,
        z: z2,
        s: s
      };
    }

    function polar(ang, r, h) {
      return project(r * Math.cos(ang), h, r * Math.sin(ang));
    }

    function avgZ(pts) {
      var i;
      var z = 0;
      for (i = 0; i < pts.length; i += 1) z += pts[i].z;
      return z / pts.length;
    }

    function resize() {
      var box = host.getBoundingClientRect();
      var cssW = Math.max(260, Math.min(box.width || 360, 420));
      var cssH = Math.round(cssW * 1.02);
      var dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.round(cssW * dpr);
      canvas.height = Math.round(cssH * dpr);
      canvas.style.width = cssW + 'px';
      canvas.style.height = cssH + 'px';
      cx = canvas.width / 2;
      cy = canvas.height * 0.5;
      SCALE = canvas.width * 1.06;
      draw();
    }

    function localAngle(e) {
      var rect = canvas.getBoundingClientRect();
      var x = e.clientX - rect.left - rect.width / 2;
      var y = e.clientY - rect.top - rect.height / 2;
      return Math.atan2(-(y / 0.55), x);
    }

    function applyImpulse(ballKick, wheelKick) {
      if (phase === 'idle' || phase === 'pocket') {
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

    function onUp() {
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
        applyImpulse(-charge, charge * 0.32);
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
        if (Math.abs(ballV) < fallW()) phase = 'fall';
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

    function poly(pts, fill, stroke, width) {
      if (!pts.length) return;
      ctx.beginPath();
      ctx.moveTo(pts[0].x, pts[0].y);
      var p;
      for (p = 1; p < pts.length; p += 1) ctx.lineTo(pts[p].x, pts[p].y);
      ctx.closePath();
      if (fill) {
        ctx.fillStyle = fill;
        ctx.fill();
      }
      if (stroke) {
        ctx.strokeStyle = stroke;
        ctx.lineWidth = width || 1;
        ctx.stroke();
      }
    }

    function ringPts(r, h, steps) {
      var pts = [];
      var i;
      for (i = 0; i <= steps; i += 1) pts.push(polar((i / steps) * Math.PI * 2, r, h));
      return pts;
    }

    function evenOdd(outer, inner, fill) {
      ctx.beginPath();
      ctx.moveTo(outer[0].x, outer[0].y);
      var i;
      for (i = 1; i < outer.length; i += 1) ctx.lineTo(outer[i].x, outer[i].y);
      ctx.closePath();
      ctx.moveTo(inner[0].x, inner[0].y);
      for (i = 1; i < inner.length; i += 1) ctx.lineTo(inner[i].x, inner[i].y);
      ctx.closePath();
      ctx.fillStyle = fill;
      ctx.fill('evenodd');
    }

    function strokeLoop(pts, stroke, width) {
      ctx.beginPath();
      ctx.moveTo(pts[0].x, pts[0].y);
      var i;
      for (i = 1; i < pts.length; i += 1) ctx.lineTo(pts[i].x, pts[i].y);
      ctx.closePath();
      ctx.strokeStyle = stroke;
      ctx.lineWidth = width;
      ctx.stroke();
    }

    function ballHeight() {
      if (phase === 'track') return 0.16;
      if (phase === 'fall') return 0.06 + Math.max(0, ballR - pocketR()) * 0.45;
      return 0.045;
    }

    function draw() {
      if (!ctx) return;
      var i;
      ctx.clearRect(0, 0, canvas.width, canvas.height);

      poly(ringPts(1.48, -0.1, 96), '#2f6a4a', null, 0);
      evenOdd(ringPts(1.16, 0.22, 64), ringPts(1.16, -0.06, 64), '#4a3018');
      for (i = 0; i < 18; i += 1) {
        var stave = (i / 18) * Math.PI * 2 - Math.PI / 2;
        if (Math.sin(stave) > 0.55) continue;
        ctx.beginPath();
        var p0 = polar(stave, 1.16, -0.05);
        var p1 = polar(stave, 1.16, 0.21);
        ctx.moveTo(p0.x, p0.y);
        ctx.lineTo(p1.x, p1.y);
        ctx.strokeStyle = 'rgba(30, 18, 8, 0.35)';
        ctx.lineWidth = 1;
        ctx.stroke();
      }
      evenOdd(ringPts(1.16, 0.22, 64), ringPts(1.03, 0.2, 64), '#c6a24a');
      evenOdd(ringPts(1.03, 0.2, 64), ringPts(0.97, 0.08, 64), '#1a120a');
      strokeLoop(ringPts(1.16, 0.22, 64), '#ead27a', Math.max(1.5, SCALE * 0.006));
      strokeLoop(ringPts(1.03, 0.2, 64), '#8a6a2a', 1);

      var layers = [];
      for (i = 0; i < N; i += 1) {
        var pa = wheelA - Math.PI / 2 + i * STEP;
        var pb = pa + STEP;
        var top = [polar(pa, 0.96, 0.035), polar(pb, 0.96, 0.035), polar(pb, 0.58, 0.05), polar(pa, 0.58, 0.05)];
        var side = [polar(pa, 0.96, -0.02), polar(pb, 0.96, -0.02), polar(pb, 0.96, 0.035), polar(pa, 0.96, 0.035)];
        var col = colorOf(EURO[i]);
        layers.push({ z: avgZ(side) - 0.01, pts: side, fill: FILL_SIDE[col], stroke: null, w: 0 });
        layers.push({
          z: avgZ(top),
          pts: top,
          fill: FILL[col],
          stroke: 'rgba(212, 175, 55, 0.35)',
          w: 1,
          label: { ang: pa + STEP / 2, n: EURO[i] }
        });
      }

      for (i = 0; i < 8; i += 1) {
        var dang = i * Math.PI / 4 + Math.PI / 8;
        var fret = [
          polar(dang - 0.045, 0.93, 0.07),
          polar(dang, 0.99, 0.16),
          polar(dang + 0.045, 0.93, 0.07),
          polar(dang, 0.9, 0.05)
        ];
        layers.push({ z: avgZ(fret), pts: fret, fill: '#d7c389', stroke: '#8a6a2a', w: 1 });
      }

      for (i = 0; i < 12; i += 1) {
        var ha0 = wheelA + (i / 12) * Math.PI * 2;
        var ha1 = wheelA + ((i + 1) / 12) * Math.PI * 2;
        var inner = [polar(ha0, 0.58, 0.05), polar(ha1, 0.58, 0.05), polar(ha1, 0.22, 0.06), polar(ha0, 0.22, 0.06)];
        layers.push({ z: avgZ(inner), pts: inner, fill: i % 2 ? '#d4b45a' : '#b8953c', stroke: null, w: 0 });
        var cone = [project(0, 0.46, 0), polar(ha0, 0.22, 0.06), polar(ha1, 0.22, 0.06)];
        layers.push({ z: avgZ(cone), pts: cone, fill: i % 2 ? '#f4eee4' : '#d9cbb3', stroke: null, w: 0 });
      }
      var cap = [];
      for (i = 0; i <= 16; i += 1) cap.push(polar(wheelA + (i / 16) * Math.PI * 2, 0.07, 0.5));
      layers.push({ z: avgZ(cap), pts: cap, fill: '#e8d27a', stroke: '#f7e7a8', w: 1 });

      var ballP = polar(ballA, ballR, ballHeight());
      layers.push({ z: ballP.z, ball: ballP });

      layers.sort(function (a, b) { return b.z - a.z; });

      for (i = 0; i < layers.length; i += 1) {
        var layer = layers[i];
        if (layer.ball) {
          var p = layer.ball;
          var rad = Math.max(5, 18 * p.s * SCALE / 280);
          ctx.beginPath();
          ctx.ellipse(p.x + rad * 0.15, p.y + rad * 0.55, rad * 1.05, rad * 0.42, 0, 0, Math.PI * 2);
          ctx.fillStyle = 'rgba(0, 0, 0, 0.32)';
          ctx.fill();
          var shine = ctx.createRadialGradient(p.x - rad * 0.28, p.y - rad * 0.38, rad * 0.08, p.x, p.y, rad);
          shine.addColorStop(0, '#fffdf8');
          shine.addColorStop(0.42, '#e6e0d2');
          shine.addColorStop(1, '#7a756c');
          ctx.beginPath();
          ctx.arc(p.x, p.y, rad, 0, Math.PI * 2);
          ctx.fillStyle = shine;
          ctx.fill();
          continue;
        }
        poly(layer.pts, layer.fill, layer.stroke, layer.w);
        if (layer.label) {
          var label = polar(layer.label.ang, 0.8, 0.055);
          ctx.save();
          ctx.translate(label.x, label.y);
          ctx.scale(Math.max(0.55, label.s * 1.15), Math.max(0.42, label.s * 0.82));
          ctx.fillStyle = '#f7f1e4';
          ctx.font = '700 12px "Noto Sans KR", sans-serif';
          ctx.textAlign = 'center';
          ctx.textBaseline = 'middle';
          ctx.fillText(String(layer.label.n), 0, 0);
          ctx.restore();
        }
      }

      if (charge > 0.4) {
        var cpts = [];
        var span = (charge / MAX_BALL) * Math.PI * 2;
        var c;
        for (c = 0; c <= 24; c += 1) cpts.push(polar(-Math.PI / 2 + (c / 24) * span, 1.1, 0.23));
        ctx.beginPath();
        ctx.moveTo(cpts[0].x, cpts[0].y);
        for (c = 1; c < cpts.length; c += 1) ctx.lineTo(cpts[c].x, cpts[c].y);
        ctx.strokeStyle = '#f45e45';
        ctx.lineWidth = Math.max(3, SCALE * 0.012);
        ctx.lineCap = 'round';
        ctx.stroke();
      }
    }

    function onLost() {
      if (dragging) onUp();
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
        var st = clamp(strength == null ? 8 : strength, 3, MAX_BALL);
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
        applyImpulse(-st, st * 0.34);
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
