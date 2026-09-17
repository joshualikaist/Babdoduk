(function (root) {
  var EURO = [0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30, 8, 23, 10, 5, 24, 16, 33, 1, 20, 14, 31, 9, 22, 18, 29, 7, 28, 12, 35, 3, 26];
  var RED = {
    1: 1, 3: 1, 5: 1, 7: 1, 9: 1, 12: 1, 14: 1, 16: 1, 18: 1, 19: 1,
    21: 1, 23: 1, 25: 1, 27: 1, 30: 1, 32: 1, 34: 1, 36: 1
  };
  var N = EURO.length;
  var STEP = (Math.PI * 2) / N;
  var MAX_BALL = 26;
  var MAX_WHEEL = 9;
  var MAT = {
    wood: '#3F2A1C',
    woodDark: '#271910',
    brass: '#9A7C45',
    brassLight: '#C4AE72',
    brassDeep: '#6A522C',
    red: '#B94632',
    redDeep: '#8A3224',
    charcoal: '#241F1A',
    charcoalSoft: '#322C26',
    green: '#536B4A',
    greenDeep: '#3E5238',
    ivory: '#F3EEE4',
    cream: '#F5F1E8',
    bowl: '#3A332C'
  };
  var LIGHT = (function () {
    var x = -0.5;
    var y = 0.82;
    var z = -0.38;
    var len = Math.sqrt(x * x + y * y + z * z);
    return { x: x / len, y: y / len, z: z / len };
  })();

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

  function hexRgb(hex) {
    hex = hex.replace('#', '');
    if (hex.length === 3) hex = hex.charAt(0) + hex.charAt(0) + hex.charAt(1) + hex.charAt(1) + hex.charAt(2) + hex.charAt(2);
    return {
      r: parseInt(hex.slice(0, 2), 16),
      g: parseInt(hex.slice(2, 4), 16),
      b: parseInt(hex.slice(4, 6), 16)
    };
  }

  function rgbStr(r, g, b) {
    return 'rgb(' + Math.round(clamp(r, 0, 255)) + ',' + Math.round(clamp(g, 0, 255)) + ',' + Math.round(clamp(b, 0, 255)) + ')';
  }

  function shadeColor(hex, amount) {
    var c = hexRgb(hex);
    var k = clamp(amount, 0.28, 1.38);
    return rgbStr(c.r * k, c.g * k, c.b * k);
  }

  function lambert(nx, ny, nz) {
    var d = nx * LIGHT.x + ny * LIGHT.y + nz * LIGHT.z;
    return 0.46 + 0.54 * Math.max(0, d);
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
    canvas.setAttribute('aria-label', opts.aria || '음식 고르는 다이얼');
    host.innerHTML = '';
    host.appendChild(canvas);
    var ctx = canvas.getContext('2d');

    var cx = 0;
    var cy = 0;
    var SCALE = 0;
    var camY = 2.04;
    var camZ = -2.58;
    var lookY = 0.12;
    var fov = 1.36;
    var ccos = 1;
    var csin = 0;
    var wheelA = 0;
    var wheelV = 0;
    var ballA = pocketCenter(0, 0);
    var ballV = 0;
    var ballR = 0.905;
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
    var layers = [];

    function trackR() { return 0.905; }
    function pocketR() { return 0.705; }
    function fallW() { return 4.2; }

    function setCamera(cssW) {
      if (cssW < 380) {
        camY = 2.32;
        camZ = -2.28;
        lookY = 0.07;
        fov = 1.44;
      } else {
        camY = 1.9;
        camZ = -2.52;
        lookY = 0.11;
        fov = 1.3;
      }
      var th = Math.atan2(lookY - camY, -camZ);
      ccos = Math.cos(th);
      csin = Math.sin(th);
    }

    function project(x, y, z) {
      var dy = y - camY;
      var dz = z - camZ;
      var y2 = dy * ccos - dz * csin;
      var z2 = dy * csin + dz * ccos;
      var s = fov / Math.max(0.35, z2);
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
      var cssW = Math.max(260, Math.min(box.width || 360, 500));
      var cssH = Math.round(cssW * (cssW < 380 ? 0.98 : 1.04));
      var dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.round(cssW * dpr);
      canvas.height = Math.round(cssH * dpr);
      canvas.style.width = cssW + 'px';
      canvas.style.height = cssH + 'px';
      cx = canvas.width / 2;
      cy = canvas.height * 0.52;
      SCALE = canvas.width * 0.88;
      setCamera(cssW);
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

    function quad(r0, h0, r1, h1, a0, a1) {
      return [polar(a0, r0, h0), polar(a1, r0, h0), polar(a1, r1, h1), polar(a0, r1, h1)];
    }

    function wallLight(midA) {
      return lambert(Math.cos(midA), 0.18, Math.sin(midA));
    }

    function ballHeight() {
      if (phase === 'fall') return 0.055 + Math.max(0, ballR - pocketR()) * 0.48;
      if (ballR > (trackR() + pocketR()) * 0.5) return 0.15;
      return 0.04;
    }

    function drawGroundShadow() {
      poly(ringPts(1.28, -0.13, 48), 'rgba(46, 33, 25, 0.12)', null, 0);
      var foot = polar(-Math.PI / 2, 0.15, -0.11);
      ctx.beginPath();
      ctx.ellipse(foot.x, foot.y + SCALE * 0.06, SCALE * 0.46, SCALE * 0.075, 0, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(46, 33, 25, 0.2)';
      ctx.fill();
    }

    function drawOuterBase() {
      evenOdd(ringPts(1.18, 0.14, 72), ringPts(1.18, -0.08, 72), shadeColor(MAT.wood, 0.68));
      var segs = 48;
      var i;
      for (i = 0; i < segs; i += 1) {
        var a0 = (i / segs) * Math.PI * 2;
        var a1 = ((i + 1) / segs) * Math.PI * 2;
        var mid = (a0 + a1) / 2;
        if (Math.sin(mid) > 0.46) continue;
        poly(quad(1.18, -0.08, 1.18, 0.14, a0, a1), shadeColor(MAT.wood, wallLight(mid) * 0.9), null, 0);
      }
      poly(ringPts(1.18, 0.14, 72), shadeColor(MAT.wood, lambert(0, 1, 0.08) * 0.82), null, 0);
    }

    function drawOuterRim(nearOnly) {
      var segs = 48;
      var i;
      for (i = 0; i < segs; i += 1) {
        var a0 = (i / segs) * Math.PI * 2;
        var a1 = ((i + 1) / segs) * Math.PI * 2;
        var mid = (a0 + a1) / 2;
        var near = Math.sin(mid) < 0.3;
        if (nearOnly && !near) continue;
        if (!nearOnly && near) continue;
        var k = wallLight(mid);
        poly(quad(1.18, 0.14, 1.18, 0.27, a0, a1), shadeColor(MAT.woodDark, k * 0.92), null, 0);
        poly(quad(1.18, 0.27, 1.08, 0.255, a0, a1), shadeColor(MAT.wood, 0.62 + k * 0.38), null, 0);
        poly(quad(1.08, 0.255, 1.03, 0.25, a0, a1), shadeColor(MAT.brass, 0.62 + k * 0.4), null, 0);
        poly(quad(1.03, 0.25, 0.975, 0.09, a0, a1), shadeColor(MAT.woodDark, k * 0.64), null, 0);
      }
      if (!nearOnly) {
        evenOdd(ringPts(1.18, 0.27, 72), ringPts(1.08, 0.255, 72), shadeColor(MAT.wood, lambert(0, 1, 0.1) * 0.95));
        evenOdd(ringPts(1.08, 0.255, 72), ringPts(1.03, 0.25, 72), shadeColor(MAT.brass, lambert(0, 1, 0.12) * 0.92));
      }
    }

    function pocketTone(kind, lit) {
      if (kind === 'red') return shadeColor(MAT.red, lit);
      if (kind === 'green') return shadeColor(MAT.green, lit);
      return shadeColor(MAT.charcoal, lit * 0.92);
    }

    function drawPocketRing() {
      var i;
      for (i = 0; i < N; i += 1) {
        var pa = wheelA - Math.PI / 2 + i * STEP;
        var pb = pa + STEP;
        var mid = pa + STEP / 2;
        var kind = colorOf(EURO[i]);
        var lit = lambert(Math.cos(mid) * 0.32, 0.92, Math.sin(mid) * 0.32);
        var side = quad(0.97, -0.012, 0.97, 0.05, pa, pb);
        var outer = [polar(pa, 0.97, 0.05), polar(pb, 0.97, 0.05), polar(pb, 0.78, 0.04), polar(pa, 0.78, 0.04)];
        var inner = [polar(pa, 0.78, 0.04), polar(pb, 0.78, 0.04), polar(pb, 0.56, 0.018), polar(pa, 0.56, 0.018)];
        var well = quad(0.56, 0.018, 0.56, 0.002, pa, pb);
        layers.push({ z: avgZ(side) - 0.012, pts: side, fill: pocketTone(kind, lit * 0.58) });
        layers.push({
          z: avgZ(outer),
          pts: outer,
          fill: pocketTone(kind, lit * 1.06),
          stroke: 'rgba(154, 124, 69, 0.28)',
          w: 0.9,
          label: { ang: mid, n: EURO[i] }
        });
        layers.push({ z: avgZ(inner), pts: inner, fill: pocketTone(kind, lit * 0.78) });
        layers.push({ z: avgZ(well), pts: well, fill: pocketTone(kind, lit * 0.5) });
      }
    }

    function drawInnerBowl() {
      var i;
      for (i = 0; i < 20; i += 1) {
        var a0 = wheelA + (i / 20) * Math.PI * 2;
        var a1 = wheelA + ((i + 1) / 20) * Math.PI * 2;
        var mid = (a0 + a1) / 2;
        var k = lambert(Math.cos(mid) * 0.22, 0.86, Math.sin(mid) * 0.22);
        var trim = quad(0.56, 0.02, 0.5, 0.016, a0, a1);
        var slope = quad(0.5, 0.016, 0.16, -0.018, a0, a1);
        layers.push({ z: avgZ(trim), pts: trim, fill: shadeColor(MAT.brassDeep, k * 0.88) });
        layers.push({ z: avgZ(slope), pts: slope, fill: shadeColor(i % 2 ? MAT.bowl : MAT.charcoalSoft, k * 0.9) });
      }
    }

    function drawHub() {
      var i;
      for (i = 0; i < 12; i += 1) {
        var a0 = wheelA + (i / 12) * Math.PI * 2;
        var a1 = wheelA + ((i + 1) / 12) * Math.PI * 2;
        var mid = (a0 + a1) / 2;
        var k = lambert(Math.cos(mid) * 0.5, 0.7, Math.sin(mid) * 0.5);
        var base = quad(0.16, -0.016, 0.11, 0.03, a0, a1);
        var taper = [polar(a0, 0.11, 0.03), polar(a1, 0.11, 0.03), polar(a1, 0.045, 0.105), polar(a0, 0.045, 0.105)];
        layers.push({ z: avgZ(base), pts: base, fill: shadeColor(MAT.brassDeep, k * 0.92) });
        layers.push({ z: avgZ(taper), pts: taper, fill: shadeColor(MAT.brass, k) });
      }
      var cap = ringPts(0.042, 0.118, 14);
      var hi = polar(-2.45, 0.012, 0.128);
      layers.push({ z: avgZ(cap) - 0.02, pts: cap, fill: shadeColor(MAT.brassLight, lambert(-0.4, 0.9, -0.2)), hubCap: hi });
    }

    function drawDeflectors() {
      var i;
      for (i = 0; i < 8; i += 1) {
        var dang = i * Math.PI / 4 + Math.PI / 8;
        var hit = deflectHit[i] > 0;
        var fret = [
          polar(dang - 0.03, 0.94, 0.08),
          polar(dang, 0.98, 0.13),
          polar(dang + 0.03, 0.94, 0.08)
        ];
        layers.push({
          z: avgZ(fret),
          pts: fret,
          fill: shadeColor(hit ? MAT.brassLight : MAT.brass, hit ? 1.2 : 0.95),
          stroke: MAT.brassDeep,
          w: 0.7
        });
      }
    }

    function drawPointer() {
      var ang = -Math.PI / 2;
      var shadow = [
        polar(ang - 0.055, 1.02, 0.22),
        polar(ang, 0.9, 0.2),
        polar(ang + 0.055, 1.02, 0.22)
      ];
      poly(shadow, 'rgba(39, 25, 16, 0.28)', null, 0);
      var body = [
        polar(ang - 0.046, 1.16, 0.34),
        polar(ang, 1.21, 0.36),
        polar(ang + 0.046, 1.16, 0.34),
        polar(ang, 0.93, 0.3)
      ];
      poly(body, MAT.ivory, shadeColor(MAT.brassDeep, 1.05), 1.4);
      var trim = [
        polar(ang - 0.018, 1.165, 0.345),
        polar(ang, 1.2, 0.355),
        polar(ang + 0.018, 1.165, 0.345),
        polar(ang, 1.08, 0.33)
      ];
      poly(trim, shadeColor(MAT.brass, 1.05), null, 0);
    }

    function drawBall() {
      var h = ballHeight();
      var p = polar(ballA, ballR, h);
      var rad = Math.max(6.4, 21 * p.s * SCALE / 280);
      if (phase === 'fall') rad *= 0.96;
      var lift = Math.max(0.35, Math.min(1.2, h / 0.15));
      ctx.beginPath();
      ctx.ellipse(p.x + rad * 0.08, p.y + rad * (0.38 + lift * 0.28), rad * (0.95 + lift * 0.15), rad * 0.32, 0, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(46, 33, 25,' + (0.28 / lift) + ')';
      ctx.fill();
      var hx = p.x - rad * 0.32;
      var hy = p.y - rad * 0.38;
      var shine = ctx.createRadialGradient(hx, hy, rad * 0.08, p.x, p.y, rad);
      shine.addColorStop(0, '#fffdf8');
      shine.addColorStop(0.38, MAT.ivory);
      shine.addColorStop(1, '#8f877c');
      ctx.beginPath();
      ctx.arc(p.x, p.y, rad, 0, Math.PI * 2);
      ctx.fillStyle = shine;
      ctx.fill();
      ctx.beginPath();
      ctx.arc(p.x - rad * 0.28, p.y - rad * 0.32, rad * 0.16, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(255, 253, 248, 0.55)';
      ctx.fill();
    }

    function drawCharge() {
      if (charge <= 0.4) return;
      var cpts = [];
      var span = (charge / MAX_BALL) * Math.PI * 1.4;
      var c;
      for (c = 0; c <= 20; c += 1) cpts.push(polar(-Math.PI / 2 - span / 2 + (c / 20) * span, 1.12, 0.27));
      ctx.beginPath();
      ctx.moveTo(cpts[0].x, cpts[0].y);
      for (c = 1; c < cpts.length; c += 1) ctx.lineTo(cpts[c].x, cpts[c].y);
      ctx.strokeStyle = shadeColor(MAT.red, 1.05);
      ctx.lineWidth = Math.max(2.5, SCALE * 0.01);
      ctx.lineCap = 'round';
      ctx.stroke();
    }

    function draw() {
      if (!ctx) return;
      var i;
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      drawGroundShadow();
      drawOuterBase();
      drawOuterRim(false);

      layers.length = 0;
      drawPocketRing();
      drawInnerBowl();
      drawHub();
      drawDeflectors();
      var ballP = polar(ballA, ballR, ballHeight());
      layers.push({ z: ballP.z, ball: true });
      layers.sort(function (a, b) { return b.z - a.z; });

      for (i = 0; i < layers.length; i += 1) {
        var layer = layers[i];
        if (layer.ball) {
          drawBall();
          continue;
        }
        poly(layer.pts, layer.fill, layer.stroke, layer.w);
        if (layer.hubCap) {
          ctx.beginPath();
          ctx.arc(layer.hubCap.x, layer.hubCap.y, Math.max(2, SCALE * 0.012), 0, Math.PI * 2);
          ctx.fillStyle = 'rgba(255, 250, 240, 0.45)';
          ctx.fill();
        }
        if (layer.label) {
          var label = polar(layer.label.ang, 0.84, 0.052);
          ctx.save();
          ctx.translate(label.x, label.y);
          ctx.rotate(layer.label.ang + Math.PI / 2);
          ctx.scale(Math.max(0.62, label.s * 1.22), Math.max(0.48, label.s * 0.86));
          ctx.fillStyle = MAT.ivory;
          ctx.font = '500 13px "Noto Sans KR", sans-serif';
          ctx.textAlign = 'center';
          ctx.textBaseline = 'middle';
          ctx.fillText(String(layer.label.n), 0, 0);
          ctx.restore();
        }
      }

      drawOuterRim(true);
      drawPointer();
      drawCharge();
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
    setCamera(360);
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
