/* 마이 밥도둑 (my.html, lab only; docs/MY_BABDODUK.md). Optional sign-in, the account's saved free-food
 * list and restaurant list counts, the private profile name, signing out, clearing saved data and
 * leaving. Login is never forced: a guest sees what this browser saved and what signing in adds.
 */
(function () {
  'use strict';

  var A = window.BabdodukAccount;
  var L = window.BabdodukLive;
  var F = window.BabdodukFreeFood;
  var app = document.getElementById('myApp');
  var toast = document.getElementById('myToast');
  if (!app || !A) return;

  var state = {
    view: 'loading',          // off | out | in | error | left
    user: null,
    client: null,
    events: [],               // account rows: {id, savedAt, seen}
    places: null,             // {want, been, again} or null when unavailable
    profile: null,
    merge: null,              // the last merge result, for its notice and 되돌리기
    feed: null,               // public events (occurrences) once loaded
    archive: null,
    panel: '',                // '' | 'clear' | 'leave'
    editing: false,
    busy: false,
    loginError: /[?&#]error(=|_description=)/.test(location.search + location.hash),
    next: (location.search.match(/[?&]next=([a-z-]{1,20})/) || [])[1] || ''
  };

  // ---- text --------------------------------------------------------------------------------------
  function lang() { return document.documentElement.lang === 'en' ? 'en' : 'ko'; }
  function t(key, fallback, vars) {
    var table = (window.BABDODUK_STR || {})[lang()] || {};
    var text = table[key] !== undefined ? table[key] : (fallback !== undefined ? fallback : key);
    Object.keys(vars || {}).forEach(function (name) { text = text.split('{' + name + '}').join(String(vars[name])); });
    return text;
  }
  function esc(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, function (ch) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch];
    });
  }
  function announce(text) {
    if (!toast) return;
    toast.textContent = '';
    setTimeout(function () { toast.textContent = text; }, 30);
  }
  function providerLabel(p) { return p === 'google' ? 'Google' : t('my.provider.kakao', '카카오'); }
  function dateText(iso) {
    var d = new Date(iso);
    if (isNaN(d)) return '';
    return new Intl.DateTimeFormat(lang() === 'en' ? 'en-US' : 'ko-KR', {
      timeZone: 'Asia/Seoul', month: 'short', day: 'numeric', weekday: 'short', hour: '2-digit', minute: '2-digit', hour12: false
    }).format(d);
  }

  // ---- data ----------------------------------------------------------------------------------------
  function loadFeed() {
    function get(url) {
      return fetch(url, { cache: 'no-cache' }).then(function (r) { if (!r.ok) throw new Error(url); return r.json(); });
    }
    return Promise.all([
      get('data/ggongbab/latest.json').catch(function () { return null; }),
      get('data/ggongbab/archive/index.json').catch(function () { return null; })
    ]).then(function (res) {
      var pub = function (list) { return F ? F.occurrences((list || []).filter(F.isPublic)) : (list || []); };
      state.feed = res[0] ? pub(res[0].events) : [];
      state.archive = res[1] ? pub(res[1].events) : [];
    });
  }
  function find(list, id) {
    for (var i = 0; i < (list || []).length; i++) if (list[i].id === id) return list[i];
    return null;
  }
  // Each saved event against the newest public data: upcoming, ended or missing (never "cancelled").
  function savedRows(now) {
    return state.events.map(function (item) {
      var live = find(state.feed, item.id);
      var past = find(state.archive, item.id);
      var seen = item.seen || {};
      var ev = live || past || { id: item.id, title: seen.title, startAt: seen.startAt, endAt: seen.endAt || null };
      var end = F ? F.eventEnd(ev) : null;
      var kind;
      if (live && F && F.isUpcoming(live, now)) kind = 'upcoming';
      else if (live || past || (end && end < now)) kind = 'ended';
      else if (state.feed === null) kind = 'checking';
      else kind = 'missing';
      var changed = kind === 'upcoming' && L ? L.changes(item, live).length > 0 : false;
      return { item: item, ev: ev, kind: kind, changed: changed };
    }).sort(function (a, b) {
      var order = { upcoming: 0, checking: 1, missing: 2, ended: 3 };
      if (order[a.kind] !== order[b.kind]) return order[a.kind] - order[b.kind];
      var x = Date.parse(a.ev.startAt) || 0, y = Date.parse(b.ev.startAt) || 0;
      return a.kind === 'ended' ? y - x : x - y;
    });
  }

  // ---- views -----------------------------------------------------------------------------------------
  function guestCount() {
    try {
      var v = JSON.parse(localStorage.getItem('babdoduk-ggongbab-saved') || 'null');
      return v && v.v === 1 && Array.isArray(v.items) ? v.items.length : 0;
    } catch (e) { return 0; }
  }
  function guestNoteHtml() {
    var n = guestCount();
    return '<p class="my-note">' + esc(n
      ? t('my.guest.count', '이 브라우저에 저장한 꽁밥 {n}개가 있어요.', { n: n })
      : t('my.guest.none', '아직 이 브라우저에 저장한 꽁밥이 없어요.')) +
      ' <a href="ggongbab.html#saved">' + esc(t('my.guest.open', '저장한 꽁밥 보기')) + '</a></p>';
  }
  function offHtml() {
    return '<section class="my-card" aria-labelledby="myOffTitle">' +
      '<h2 class="my-h2" id="myOffTitle">' + esc(t('my.off.title', '로그인은 준비 중이에요')) + '</h2>' +
      '<p class="my-text">' + esc(t('my.off.body', '지금은 저장한 꽁밥이 이 브라우저에만 남아요. 로그인이 열리면 여기서 알려 드릴게요.')) + '</p>' +
      guestNoteHtml() + '</section>';
  }
  function outHtml() {
    var inTalk = L && L.inTalkApp && L.inTalkApp(navigator.userAgent);
    var html = '<section class="my-card" aria-labelledby="myOutTitle">';
    html += '<h2 class="my-h2" id="myOutTitle">' + esc(t('my.out.title', '로그인하면 이렇게 돼요')) + '</h2>';
    html += '<ul class="my-benefits">' +
      '<li>' + esc(t('my.out.b1', '저장한 꽁밥과 먹킷리스트를 휴대폰과 컴퓨터에서 함께 봐요')) + '</li>' +
      '<li>' + esc(t('my.out.b2', '이 브라우저에 저장한 것은 로그인할 때 계정에 합쳐져요')) + '</li>' +
      '<li>' + esc(t('my.out.b3', '프로필과 메모는 나만 봐요')) + '</li></ul>';
    if (state.loginError) html += '<p class="my-alert" role="alert">' + esc(t('my.out.failed', '로그인하지 못했어요. 다시 시도해 주세요.')) + '</p>';
    html += '<div class="my-login">';
    html += '<button type="button" class="my-login-btn is-kakao" data-my-login="kakao">' + esc(t('my.out.kakao', '카카오로 계속하기')) + '</button>';
    if (inTalk) {
      html += '<p class="my-note">' + esc(t('my.out.googleTalk', 'Google 로그인은 카카오톡 안에서 막혀 있어요. 기본 브라우저에서 열어 주세요.')) +
        ' <a href="' + esc(L.openExternalUrl(location.href)) + '">' + esc(t('my.out.openExternal', '기본 브라우저로 열기')) + '</a></p>';
    } else {
      html += '<button type="button" class="my-login-btn is-google" data-my-login="google">' + esc(t('my.out.google', 'Google로 계속하기')) + '</button>';
    }
    html += '</div>';
    html += '<p class="my-fine">' + esc(t('my.out.fine', 'KAIST 인증은 필요 없어요. 로그인했다고 모든 꽁밥에 참여할 수 있는 건 아니에요: 참여 조건은 행사마다 달라요.')) + '</p>';
    html += guestNoteHtml();
    return html + '</section>';
  }
  function mergeHtml() {
    var m = state.merge;
    if (!m || (!m.events && !m.places && !(m.conflicts || []).length)) return '';
    var parts = [];
    if (m.events) parts.push(t('my.merge.events', '꽁밥 {n}개', { n: m.events }));
    if (m.places) parts.push(t('my.merge.places', '식당 {n}곳', { n: m.places }));
    var html = '<div class="my-merge" role="status">';
    if (parts.length) {
      html += '<p>' + esc(t('my.merge.done', '이 브라우저에 저장한 {what}을 계정에 합쳤어요.', { what: parts.join(', ') })) + '</p>';
      html += '<p class="my-fine">' + esc(t('my.merge.hint', '내 것이 아니면 되돌릴 수 있어요. 이 브라우저의 목록은 그대로 남아요.')) + '</p>';
      html += '<button type="button" class="btn btn-secondary my-small" data-my-undo>' + esc(t('my.merge.undo', '되돌리기')) + '</button>';
    }
    if ((m.conflicts || []).length) {
      html += '<p class="my-fine">' + esc(t('my.merge.conflicts', '메모가 서로 다른 식당 {n}곳은 계정 메모를 그대로 두었어요.', { n: m.conflicts.length })) + '</p>';
    }
    return html + '<button type="button" class="my-close" data-my-merge-close aria-label="' + esc(t('my.close', '닫기')) + '"><span aria-hidden="true">×</span></button></div>';
  }
  function savedHtml(now) {
    var rows = savedRows(now);
    var html = '<section class="my-card" aria-labelledby="mySavedTitle">';
    html += '<h2 class="my-h2" id="mySavedTitle"><span aria-hidden="true">★</span> ' + esc(t('my.saved.title', '저장한 꽁밥')) +
      ' <span class="my-n">' + rows.length + '</span></h2>';
    if (!rows.length) {
      html += '<p class="my-text">' + esc(t('my.saved.empty', '아직 저장한 꽁밥이 없어요. 오늘의 꽁밥에서 ☆를 눌러 보세요.')) + '</p>';
    } else {
      html += '<ol class="my-list">' + rows.map(function (row) {
        var tag = { upcoming: '', checking: t('my.saved.checking', '확인 중'), missing: t('my.saved.missing', '목록에서 빠짐'), ended: t('my.saved.ended', '지난 꽁밥') }[row.kind];
        var tags = (row.changed ? '<span class="my-tag is-changed">' + esc(t('my.saved.changed', '변경됨')) + '</span>' : '') +
          (tag ? '<span class="my-tag is-' + row.kind + '">' + esc(tag) + '</span>' : '');
        var title = esc(row.ev.title || (row.item.seen || {}).title || '');
        var body = '<span class="my-when">' + esc(dateText(row.ev.startAt)) + '</span><span class="my-what">' + title + '</span>';
        var main = row.kind === 'upcoming'
          ? '<a class="my-row-link" href="' + esc(L ? L.eventLink(row.item.id) : 'ggongbab.html') + '">' + body + '</a>'
          : '<p class="my-row-link is-static">' + body + '</p>';
        // Owner 2026-11-12: a saved event can be removed right here, without going to 오늘의 꽁밥.
        var unstar = '<button type="button" class="my-unstar" data-my-unstar="' + esc(row.item.id) + '" aria-pressed="true" aria-label="' +
          esc(t('my.saved.remove', '저장 취소: {title}', { title: row.ev.title || (row.item.seen || {}).title || '' })) +
          '"><span aria-hidden="true">★</span></button>';
        return '<li class="my-row is-' + row.kind + '">' + main + (tags ? '<span class="my-tags">' + tags + '</span>' : '') + unstar + '</li>';
      }).join('') + '</ol>';
      if (rows.some(function (r) { return r.kind === 'missing'; })) {
        html += '<p class="my-fine">' + esc(t('my.saved.missingNote', '목록에서 빠진 꽁밥은 취소됐거나 내용이 바뀌었을 수 있어요. 공지를 확인하세요.')) + '</p>';
      }
    }
    html += '<p class="my-fine"><a href="ggongbab.html">' + esc(t('my.saved.manage', '오늘의 꽁밥에서 저장·삭제하기')) + '</a></p>';
    return html + '</section>';
  }
  function placesHtml() {
    var p = state.places;
    var html = '<section class="my-card" aria-labelledby="myPlacesTitle">';
    html += '<h2 class="my-h2" id="myPlacesTitle"><span aria-hidden="true">🍜</span> ' + esc(t('my.places.title', '먹킷리스트')) + '</h2>';
    if (!p) {
      html += '<p class="my-text">' + esc(t('my.places.off', '먹킷리스트를 불러오지 못했어요.')) + '</p>';
    } else if (!p.want && !p.been && !p.again) {
      html += '<p class="my-text">' + esc(t('my.places.empty', '아직 저장한 식당이 없어요. 밥약 메이커에서 식당을 저장할 수 있어요.')) + '</p>';
    } else {
      html += '<ul class="my-counts">' +
        '<li><span>' + esc(t('my.places.want', '가고 싶어')) + '</span><b>' + p.want + '</b></li>' +
        '<li><span>' + esc(t('my.places.been', '가봤어')) + '</span><b>' + p.been + '</b></li>' +
        '<li><span>' + esc(t('my.places.again', '또 갈래')) + '</span><b>' + p.again + '</b></li></ul>';
    }
    html += '<p class="my-fine"><a href="bobyak.html">' + esc(t('my.places.open', '밥약 메이커 열기')) + '</a> · ' +
      esc(t('my.places.private', '메모는 나만 봐요')) + '</p>';
    return html + '</section>';
  }
  function accountHtml() {
    var user = state.user;
    var linked = A.providersOf(user);
    var name = state.profile && state.profile.display_name;
    var html = '<section class="my-card" aria-labelledby="myAccountTitle">';
    html += '<h2 class="my-h2" id="myAccountTitle"><span aria-hidden="true">👤</span> ' + esc(t('my.account.title', '내 정보')) + '</h2>';
    html += '<dl class="my-facts">';
    html += '<dt>' + esc(t('my.account.name', '표시 이름')) + '</dt><dd>';
    if (state.editing) {
      html += '<form class="my-name-form" data-my-name-form><label class="my-sr" for="myName">' + esc(t('my.account.name', '표시 이름')) + '</label>' +
        '<input id="myName" class="my-input" maxlength="40" autocomplete="nickname" value="' + esc(name || A.providerName(user)) + '" />' +
        '<button type="submit" class="btn btn-primary my-small">' + esc(t('my.account.save', '저장')) + '</button>' +
        '<button type="button" class="btn btn-secondary my-small" data-my-name-cancel>' + esc(t('my.cancel', '취소')) + '</button></form>';
    } else {
      html += '<span>' + esc(name || t('my.account.noName', '정하지 않음')) + '</span> ' +
        '<button type="button" class="my-link-btn" data-my-name-edit>' + esc(t('my.account.edit', '바꾸기')) + '</button>';
    }
    html += '</dd>';
    html += '<dt>' + esc(t('my.account.with', '로그인 방법')) + '</dt><dd>' +
      (linked.length ? linked.map(function (p) { return '<span class="my-chip">' + esc(providerLabel(p)) + '</span>'; }).join(' ') : '—') + '</dd>';
    html += '</dl>';
    html += '<p class="my-fine">' + esc(t('my.account.privateNote', '프로필은 공개되지 않아요. 이메일은 받지 않거나 받아도 화면에 쓰지 않아요.')) + '</p>';
    var missing = A.PROVIDERS.filter(function (p) { return linked.indexOf(p) === -1; });
    // Google refuses the talk app's own browser, and the default browser opens without this session, so
    // linking Google there starts with signing in again outside the app.
    var inTalk = L && L.inTalkApp && L.inTalkApp(navigator.userAgent);
    var linkable = missing.filter(function (p) { return !(inTalk && p === 'google'); });
    if (missing.length) {
      if (linkable.length) {
        html += '<div class="my-row-actions">' + linkable.map(function (p) {
          return '<button type="button" class="btn btn-secondary my-small" data-my-link="' + p + '">' +
            esc(t('my.account.link', '{p} 로그인도 연결', { p: providerLabel(p) })) + '</button>';
        }).join('') + '</div>';
      }
      if (linkable.length < missing.length) {
        html += '<p class="my-note">' + esc(t('my.account.linkGoogleTalk', 'Google 연결은 카카오톡 안에서 막혀 있어요. 기본 브라우저에서 카카오로 로그인한 뒤 연결해 주세요.')) +
          ' <a href="' + esc(L.openExternalUrl(location.href)) + '">' + esc(t('my.out.openExternal', '기본 브라우저로 열기')) + '</a></p>';
      }
      html += '<p class="my-fine">' + esc(t('my.account.linkNote', '같은 사람이 두 방법으로 따로 가입하면 저장 목록이 나뉘어요. 연결하면 한 계정이 돼요.')) + '</p>';
    }
    html += '<div class="my-row-actions"><button type="button" class="btn btn-secondary" data-my-signout>' + esc(t('my.account.signout', '로그아웃')) + '</button></div>';
    html += '<p class="my-fine">' + esc(t('my.account.signoutNote', '이 기기에서만 로그아웃해요. 이 브라우저에 따로 저장한 목록은 그대로 남아요.')) + '</p>';
    return html + '</section>';
  }
  function dangerHtml(now) {
    var html = '<section class="my-card is-danger" aria-labelledby="myDangerTitle">';
    html += '<h2 class="my-h2" id="myDangerTitle">' + esc(t('my.danger.title', '데이터 지우기·탈퇴')) + '</h2>';
    if (state.panel === 'clear') {
      html += '<div class="my-confirm" role="group" aria-labelledby="myClearQ"><p id="myClearQ" class="my-text">' +
        esc(t('my.clear.q', '계정에 저장한 꽁밥, 먹킷리스트, 메모를 모두 지울까요? 계정은 남아요.')) + '</p>' +
        '<label class="my-check"><input type="checkbox" id="myClearBrowser" /> ' + esc(t('my.clear.browser', '이 브라우저에 저장한 목록도 지우기')) + '</label>' +
        '<div class="my-row-actions"><button type="button" class="btn btn-primary my-small" data-my-clear-yes>' + esc(t('my.clear.yes', '모두 지우기')) + '</button>' +
        '<button type="button" class="btn btn-secondary my-small" data-my-panel="">' + esc(t('my.cancel', '취소')) + '</button></div></div>';
    } else if (state.panel === 'leave') {
      var fresh = A.signedInRecently(state.user, now);
      html += '<div class="my-confirm" role="group" aria-labelledby="myLeaveQ"><p id="myLeaveQ" class="my-text">' +
        esc(t('my.leave.q', '탈퇴하면 계정과 저장한 꽁밥, 먹킷리스트, 메모, 공유 리스트가 모두 지워지고 되돌릴 수 없어요.')) + '</p>' +
        '<p class="my-fine">' + esc(t('my.leave.keep', '결제·주문 정보를 받지 않아 법으로 따로 보관하는 개인정보는 없어요. Google·카카오 쪽 연결 기록은 각 계정 설정에서 지울 수 있어요.')) + '</p>';
      if (!fresh) {
        html += '<p class="my-text">' + esc(t('my.leave.reauth', '본인 확인을 위해 한 번 더 로그인해 주세요.')) + '</p>' +
          '<div class="my-row-actions">' + A.providersOf(state.user).map(function (p) {
            return '<button type="button" class="btn btn-primary my-small" data-my-reauth="' + p + '">' +
              esc(t('my.leave.reauthWith', '{p}로 다시 로그인', { p: providerLabel(p) })) + '</button>';
          }).join('') + '<button type="button" class="btn btn-secondary my-small" data-my-panel="">' + esc(t('my.cancel', '취소')) + '</button></div>';
      } else {
        html += '<label class="my-check"><input type="checkbox" id="myLeaveSure" /> ' + esc(t('my.leave.sure', '모두 지워지는 것을 확인했어요')) + '</label>' +
          '<label class="my-check"><input type="checkbox" id="myLeaveBrowser" /> ' + esc(t('my.clear.browser', '이 브라우저에 저장한 목록도 지우기')) + '</label>' +
          '<div class="my-row-actions"><button type="button" class="btn btn-primary my-small" data-my-leave-yes>' + esc(t('my.leave.yes', '탈퇴하기')) + '</button>' +
          '<button type="button" class="btn btn-secondary my-small" data-my-panel="">' + esc(t('my.cancel', '취소')) + '</button></div>';
      }
      html += '</div>';
    } else {
      html += '<div class="my-row-actions"><button type="button" class="btn btn-secondary my-small" data-my-panel="clear">' + esc(t('my.clear.open', '저장한 데이터 지우기')) + '</button>' +
        '<button type="button" class="btn btn-secondary my-small" data-my-panel="leave">' + esc(t('my.leave.open', '탈퇴하기')) + '</button></div>';
    }
    return html + '</section>';
  }
  function render() {
    var now = new Date();
    var html = '';
    if (state.view === 'loading') html = '<p class="my-status">' + esc(t('my.loading', '불러오는 중')) + '</p>';
    else if (state.view === 'off') html = offHtml();
    else if (state.view === 'out') html = outHtml();
    else if (state.view === 'left') html = '<section class="my-card"><h2 class="my-h2">' + esc(t('my.left.title', '탈퇴했어요')) + '</h2><p class="my-text">' +
      esc(t('my.left.body', '계정과 저장한 데이터를 모두 지웠어요. 그동안 고마웠어요.')) + '</p><p class="my-fine"><a href="index.html">' + esc(t('my.left.home', '홈으로')) + '</a></p></section>';
    else if (state.view === 'error') html = '<section class="my-card"><h2 class="my-h2">' + esc(t('my.error.title', '계정 정보를 불러오지 못했어요')) + '</h2>' +
      '<p class="my-text">' + esc(t('my.error.body', '잠시 뒤 다시 시도해 주세요. 저장한 꽁밥은 이 브라우저에서 계속 쓸 수 있어요.')) + '</p>' +
      '<div class="my-row-actions"><button type="button" class="btn btn-primary my-small" data-my-retry>' + esc(t('my.retry', '다시 시도')) + '</button>' +
      (state.user ? '<button type="button" class="btn btn-secondary my-small" data-my-signout>' + esc(t('my.account.signout', '로그아웃')) + '</button>' : '') + '</div></section>';
    else {
      var name = (state.profile && state.profile.display_name) || '';
      html = '<p class="my-hello">' + esc(name ? t('my.hello', '{name}님, 반가워요', { name: name }) : t('my.helloNoName', '로그인했어요')) + '</p>' +
        mergeHtml() + savedHtml(now) + placesHtml() + accountHtml() + dangerHtml(now);
    }
    app.setAttribute('aria-busy', state.busy ? 'true' : 'false');
    app.innerHTML = html;
  }

  // ---- flow ------------------------------------------------------------------------------------------
  function loadAccount() {
    var c = state.client, uid = state.user.id;
    return A.mergeGuest(c, uid).then(function (m) { state.merge = m; }, function () { state.merge = null; })
      .then(function () {
        var store = A.createRemoteStore(c, uid, onStoreChange);
        return Promise.all([
          store.reload().then(function (s) { state.store = s; state.events = s.list(); }),
          A.loadProfile(c, uid).then(function (p) { state.profile = p; }),
          A.placeCounts(c).then(function (p) { state.places = p; }, function () { state.places = null; })
        ]);
      }).then(function () {
        if (!state.profile) {
          // First visit: keep the provider's name as the private display name, editable or clearable.
          var name = A.providerName(state.user);
          if (name) return A.saveProfile(c, uid, name).then(function (n) { state.profile = { display_name: n }; }, function () { return null; });
        }
      });
  }
  function onStoreChange(kind) {
    if (kind !== 'failed') return;
    // A removal the server refused is put back by the store: show the list as it really is.
    if (state.store && state.view === 'in') { state.events = state.store.list(); render(); }
    announce(t('my.failed', '저장하지 못했어요. 다시 시도해 주세요.'));
  }
  function start() {
    if (!A.available()) { state.view = 'off'; render(); return; }
    state.view = 'loading'; render();
    A.client().then(function (c) {
      state.client = c;
      return A.currentUser();
    }).then(function (user) {
      state.user = user;
      if (!user) { state.view = 'out'; render(); return; }
      return Promise.all([loadAccount(), loadFeed()]).then(function () {
        state.view = 'in';
        if (state.next === 'leave') state.panel = 'leave';
        if (state.next === 'linked') announce(state.loginError ? t('my.account.linkFail', '지금은 로그인 방법을 연결할 수 없어요') : t('my.account.linked', '로그인 방법을 연결했어요'));
        if (state.next) history.replaceState(null, '', location.pathname);
        render();
      });
    }).catch(function () { state.view = 'error'; render(); });
  }
  function busy(on) { state.busy = on; app.setAttribute('aria-busy', on ? 'true' : 'false'); }

  app.addEventListener('click', function (e) {
    var el;
    if (state.busy) return;
    if ((el = e.target.closest('[data-my-login]'))) {
      busy(true);
      A.signIn(el.getAttribute('data-my-login')).catch(function () {
        busy(false); announce(t('my.out.failed', '로그인하지 못했어요. 다시 시도해 주세요.'));
      });
      return;
    }
    if ((el = e.target.closest('[data-my-reauth]'))) {
      busy(true);
      A.signIn(el.getAttribute('data-my-reauth'), 'leave').catch(function () {
        busy(false); announce(t('my.out.failed', '로그인하지 못했어요. 다시 시도해 주세요.'));
      });
      return;
    }
    if ((el = e.target.closest('[data-my-link]'))) {
      busy(true);
      A.linkProvider(el.getAttribute('data-my-link')).catch(function () {
        busy(false); announce(t('my.account.linkFail', '지금은 로그인 방법을 연결할 수 없어요'));
      });
      return;
    }
    if (e.target.closest('[data-my-signout]')) {
      busy(true);
      A.signOut().then(function () {
        busy(false); state.user = null; state.view = 'out'; render();
        announce(t('my.account.signedOut', '로그아웃했어요'));
      }, function () { busy(false); announce(t('my.failed', '저장하지 못했어요. 다시 시도해 주세요.')); });
      return;
    }
    if ((el = e.target.closest('[data-my-unstar]'))) {
      var id = el.getAttribute('data-my-unstar');
      var shown = Array.prototype.map.call(app.querySelectorAll('[data-my-unstar]'), function (b) { return b.getAttribute('data-my-unstar'); });
      var at = shown.indexOf(id);
      if (!state.store || !state.store.remove(id)) { announce(t('my.failed', '저장하지 못했어요. 다시 시도해 주세요.')); return; }
      state.events = state.store.list();
      render();
      announce(t('my.saved.removed', '저장을 취소했어요'));
      // Focus stays in the list: the star now in the removed row's place, the last one, or the heading.
      var stars = app.querySelectorAll('[data-my-unstar]');
      var heading = document.getElementById('mySavedTitle');
      if (stars.length) stars[Math.min(at, stars.length - 1)].focus();
      else if (heading) { heading.setAttribute('tabindex', '-1'); heading.focus(); }
      return;
    }
    if (e.target.closest('[data-my-retry]')) { start(); return; }
    if (e.target.closest('[data-my-merge-close]')) { state.merge = null; render(); return; }
    if (e.target.closest('[data-my-undo]')) {
      busy(true);
      A.undoMerge(state.client, state.merge).then(function () {
        state.merge = null;
        return state.store.reload();
      }).then(function (s) {
        busy(false); state.events = s.list(); render();
        announce(t('my.merge.undone', '합친 것을 되돌렸어요'));
      }, function () { busy(false); announce(t('my.failed', '저장하지 못했어요. 다시 시도해 주세요.')); });
      return;
    }
    if ((el = e.target.closest('[data-my-panel]'))) {
      state.panel = el.getAttribute('data-my-panel'); render();
      var focus = app.querySelector('.my-confirm input, .my-confirm button, [data-my-panel="' + (state.panel ? '' : 'clear') + '"]');
      if (focus) focus.focus();
      return;
    }
    if (e.target.closest('[data-my-name-edit]')) {
      state.editing = true; render();
      var input = document.getElementById('myName');
      if (input) { input.focus(); input.select(); }
      return;
    }
    if (e.target.closest('[data-my-name-cancel]')) { state.editing = false; render(); return; }
    if (e.target.closest('[data-my-clear-yes]')) {
      var alsoBrowser = document.getElementById('myClearBrowser');
      alsoBrowser = !!(alsoBrowser && alsoBrowser.checked);
      busy(true);
      A.clearSavedData(state.client).then(function () {
        if (alsoBrowser) A.clearBrowserCopy();
        state.events = []; state.places = { want: 0, been: 0, again: 0 }; state.panel = ''; state.merge = null;
        busy(false); render(); announce(t('my.clear.done', '저장한 데이터를 지웠어요'));
      }, function () { busy(false); announce(t('my.failed', '저장하지 못했어요. 다시 시도해 주세요.')); });
      return;
    }
    if (e.target.closest('[data-my-leave-yes]')) {
      var sure = document.getElementById('myLeaveSure');
      if (!sure || !sure.checked) { announce(t('my.leave.needSure', '확인란을 먼저 체크해 주세요')); if (sure) sure.focus(); return; }
      var wipe = document.getElementById('myLeaveBrowser');
      wipe = !!(wipe && wipe.checked);
      busy(true);
      A.deleteAccount(state.client).then(function () {
        if (wipe) A.clearBrowserCopy();
        busy(false); state.user = null; state.view = 'left'; render();
        announce(t('my.left.title', '탈퇴했어요'));
      }, function () {
        busy(false);
        announce(t('my.leave.fail', '탈퇴하지 못했어요. 다시 로그인한 뒤 시도해 주세요.'));
      });
    }
  });
  app.addEventListener('submit', function (e) {
    if (!e.target.closest('[data-my-name-form]')) return;
    e.preventDefault();
    var input = document.getElementById('myName');
    busy(true);
    A.saveProfile(state.client, state.user.id, input ? input.value : '').then(function (name) {
      state.profile = { display_name: name || null }; state.editing = false;
      busy(false); render(); announce(t('my.account.saved', '저장했어요'));
    }, function () { busy(false); announce(t('my.failed', '저장하지 못했어요. 다시 시도해 주세요.')); });
  });
  document.addEventListener('babdoduk-lang', render);
  start();
})();
