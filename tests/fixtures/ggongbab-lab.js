/* Synthetic data for lab-ggongbab.html?fixture=1: the free-food feed, past listings, campus news and
   the cafeteria week, all relative to the page clock (a fixed-clock check sees the same week).
   It lives with the tests and is never deployed (.vercelignore): js/ggongbab.js loads it only in
   fixture mode, from the local server (python scripts/check_ggongbab_ui.py --serve). */
(function (global) {
  var KST_OFFSET = 9 * 60;
  function toKst(iso) {
    var d = iso ? new Date(iso) : new Date();
    if (isNaN(d.getTime())) d = new Date();
    return new Date(d.getTime() + (d.getTimezoneOffset() + KST_OFFSET) * 60000);
  }
  function ymd(d) {
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
  }
  function dateHeading(isoDate) {
    if (!isoDate) return '';
    var parts = String(isoDate).split('-');
    if (parts.length < 3) return isoDate;
    var d = new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]));
    var lang = global.babdodukGetLang ? global.babdodukGetLang() : 'ko';
    var dows = lang === 'en' ? ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
      : ['일요일', '월요일', '화요일', '수요일', '목요일', '금요일', '토요일'];
    if (lang === 'en') {
      var months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
      return months[d.getMonth()] + ' ' + d.getDate() + ' · ' + dows[d.getDay()];
    }
    return (d.getMonth() + 1) + '월 ' + d.getDate() + '일 · ' + dows[d.getDay()];
  }
  function utcDay(isoDate) {
    var p = String(isoDate || '').split('-');
    if (p.length < 3) return null;
    var time = Date.UTC(Number(p[0]), Number(p[1]) - 1, Number(p[2]));
    return isNaN(time) ? null : time;
  }
  function addDays(d, n) { var x = new Date(d.getTime()); x.setDate(x.getDate() + n); return x; }

  // The free-food feed: ten upcoming events this week, long titles and texts, every source.
  function freeFeed(today) {
    function stamp(day, hour) { return ymd(addDays(today, day)) + 'T' + hour + ':00:00+09:00'; }
    var titles = ['캠퍼스 진로 이야기와 점심 한 끼','커피 한 잔, 연구 이야기','함께 나누는 오후의 다과','아이디어와 피자를 나누는 저녁','오늘 신청하는 캠퍼스 워크숍','미리 만나는 연구실 오픈데이','새로운 친구와 함께하는 점심','아주 긴 제목으로 확인하는 캠퍼스 진로 탐색과 융합 연구 협력 그리고 함께하는 따뜻한 식사에 관한 특별한 이야기','긴 소개글이 있는 캠퍼스 모임','다양한 전공이 함께하는 교류회'];
    var sourceCycle = [
      [{ type: 'dooray', name: 'Dooray' }],
      [{ type: 'portal', name: 'KAIST Portal' }],
      [{ type: 'kaist_public', name: 'KAIST 공지', url: 'https://example.org/events' }],
      [{ type: 'manual', name: 'Manual', url: 'https://example.org/events' }]
    ];
    var events = [];
    for (var i = 0; i < 10; i++) {
      var day = i < 3 ? 0 : i === 3 ? 1 : Math.min(2, 7 - (today.getDay() || 7));
      events.push({
        id: 'fixture-' + i,
        title: titles[i],
        summary: i === 8 ? '누구나 편하게 모여 새로운 연구와 진로에 관한 생각을 나눕니다. '.repeat(12) : '관심 있는 이야기를 나누고, 준비된 음식을 함께 즐겨 보세요.',
        startAt: stamp(day, i === 0 ? '12' : i === 1 ? '15' : '18'),
        endAt: stamp(day, i === 0 ? '13' : i === 1 ? '16' : '19'),
        location: { building: 'N1', room: i === 6 ? '' : '101호', name: 'KI빌딩' },
        food: { provided: 'true', type: i === 0 ? 'lunchbox' : i === 1 ? 'beverage' : i === 2 ? 'refreshment' : i === 8 ? 'snack' : 'meal', description: i === 0 ? '점심 도시락' : i === 1 ? '커피' : i === 2 ? '커피 · 다과' : i === 8 ? '샌드위치' : '피자 제공' },
        registration: { required: i === 1 ? 'false' : 'true', deadline: i === 4 ? stamp(0, '23') : null, url: i === 0 || i === 4 ? 'https://example.org/register' : '' },
        organizer: i === 9 ? '다양한 전공과 연구실이 함께 기획하고 운영하는 캠퍼스 교류 및 협력 준비위원회'.repeat(3) : '',
        eligibility: i === 9 ? 'KAIST 학부생과 대학원생 및 다양한 연구에 관심 있는 모든 구성원 '.repeat(5) : 'KAIST 학부 및 대학원생',
        sources: sourceCycle[i % 4]
      });
    }
    events[7].title = events[7].title.repeat(3);
    return { generatedAt: new Date().toISOString(), count: events.length, events: events, _preview: { publicCount: events.length, explicitFood: events.length } };
  }

  // Fixture past listings, relative to the fixture clock: what an archive may hold, plus rows
  // the page must still refuse (under review, unknown food, older than the window, not ended).
  function archive(today, windowDays) {
    function at(days, hour) { return ymd(addDays(today, days)) + 'T' + hour + ':00:00+09:00'; }
    var titles = ['지난주 진로 특강과 점심 도시락', '연구실 오픈데이 다과', '아주 긴 제목으로 확인하는 지난 캠퍼스 교류회와 함께 나눈 저녁 식사에 관한 기록 '.repeat(2),
      '대학원 설명회 샌드위치', '동아리 박람회 간식', '학과 간담회 피자', '국제 교류 커피 모임'];
    var events = titles.map(function (title, i) {
      return {
        id: 'past-' + i, title: title, summary: '지난 안내입니다.',
        startAt: at(-1 - i * 3, '12'), endAt: at(-1 - i * 3, '13'),
        location: { building: 'N1', room: '101호', name: 'KI빌딩' },
        food: { provided: 'true', type: i % 2 ? 'snack' : 'lunchbox', description: i % 2 ? '다과' : '점심 도시락' },
        organizer: '', eligibility: '',
        sources: i === 0 ? [{ type: 'kaist_public', name: 'KAIST 공지', url: 'https://example.org/notice' }]
          : i === 1 ? [{ type: 'manual', name: 'Manual', url: 'javascript:alert(1)' }] : [{ type: 'dooray', name: 'Dooray' }]
      };
    });
    // Old data may still carry sign-up fields; the page must never render them.
    events[0].registration = { required: 'true', url: 'https://example.org/register', deadline: at(-3, '18') };
    events.push({ id: 'past-review', title: '검토 중', startAt: at(-2, '12'), food: { provided: 'true' }, needs_review: true, sources: [] });
    events.push({ id: 'past-unknown', title: '음식 미확인', startAt: at(-2, '12'), food: { provided: 'unknown' }, sources: [] });
    events.push({ id: 'past-old', title: '오래된 기록', startAt: at(-45, '12'), endAt: at(-45, '13'), food: { provided: 'true' }, sources: [] });
    events.push({ id: 'past-future', title: '아직 안 끝남', startAt: at(2, '12'), food: { provided: 'true' }, sources: [] });
    return { generatedAt: new Date().toISOString(), windowDays: windowDays, count: events.length, events: events };
  }

  // Campus food news: one item dated today.
  function news(today) {
    return { items: [{ id: 'news-00000000000000000000000000000001', contentType: 'campus_food_news',
      noticeDate: ymd(today), title: '교내 새 식당 오픈 안내', summary: '점심 영업을 시작합니다.',
      hasFreeOffer: false, sources: [{ type: 'portal', name: 'KAIST 포탈' }] }] };
  }

  // Today's cafeteria menus; `stale` dates them yesterday. The places are the real ones, in their
  // order (data/content/labels.json `restaurants`); the menus are invented.
  function menu(stale, now) {
    var today = now || toKst();
    var date = stale ? ymd(new Date(today.getFullYear(), today.getMonth(), today.getDate() - 1)) : ymd(today);
    var longName = '아주 긴 메뉴 이름으로 확인하는 특제 돈가스 덮밥과 계절 나물 모둠';
    return {
      date: date,
      dateLabel: dateHeading(date),
      fetchedAt: new Date().toISOString(),
      source: 'fixture',
      restaurants: [
        { id: 'fclt', name: '카이마루 N11', building: 'N11',
          breakfast: { hours: '', items: ['쌀밥', '사골파국', '너비아니구이'], price: '3,500원', kcal: '623 kcal' },
          lunch: { hours: '', items: ['자율코너', '쌀밥', '시금치된장국', '닭살고추장볶음', '목이버섯굴소스볶음', '열무겉절이', '맛김치', '야채샐러드'], price: '5,500원', kcal: '1,292 kcal' },
          dinner: { hours: '', items: ['쌀밥', '된장찌개', '제육볶음'], price: '5,500원', kcal: '1,180 kcal' } },
        { id: 'west', name: '서맛골 W2', building: 'W2',
          breakfast: { hours: '', items: [] },
          lunch: { hours: '', items: ['비빔밥', '미역국', '김치'], price: '4,000원', kcal: '' },
          dinner: { hours: '', items: ['라면', '김밥'], price: '4,000원', kcal: '' } },
        { id: 'east1', name: '동맛골 학생식당 E5', building: 'E5',
          breakfast: { hours: '', items: [] },
          lunch: { hours: '', items: ['백반', '콩나물국'], price: '', kcal: '980 kcal' },
          dinner: { hours: '', items: ['볶음밥', '계란국'], price: '', kcal: '1,050 kcal' } },
        { id: 'east2', name: '동맛골 교직원식당 E5', building: 'E5',
          breakfast: { hours: '', items: [] },
          lunch: { hours: '', items: ['돈가스', '우동', '샐러드'], price: '6,000원', kcal: '1,410 kcal' },
          dinner: { hours: '', items: ['카레라이스', '단무지'], price: '5,500원', kcal: '1,200 kcal' } },
        { id: 'emp', name: '교수회관 N6', building: 'N6',
          breakfast: { hours: '', items: [] },
          lunch: { hours: '', items: ['한정식', '국', '나물'], price: '8,000원', kcal: '1,100 kcal' },
          dinner: { hours: '', items: [] } },
        { id: 'icc', name: '문지캠퍼스', building: '문지',
          breakfast: { hours: '', items: ['토스트', '우유'], price: '3,000원', kcal: '' },
          lunch: { hours: '', items: [longName, '스프', '샐러드', '피클', '후식 과일', '미니 빵', '수프 리필', '계절 음료'], price: '7,000원', kcal: '1,520 kcal' },
          dinner: { hours: '', items: [] } }
      ]
    };
  }

  // Lab fixture for the other days of the week: weekdays have menus (a different number of
  // places each day), Saturday has lunch only, Sunday has nothing published.
  function menuDay(isoDate) {
    var time = utcDay(isoDate);
    if (time == null) return null;
    var dow = new Date(time).getUTCDay();
    if (dow === 0) return null;
    var base = menu(false);
    var keep = dow === 6 ? 2 : Math.max(2, base.restaurants.length - (dow % 3));
    var restaurants = base.restaurants.slice(0, keep).map(function (row) {
      var copy = JSON.parse(JSON.stringify(row));
      if (dow === 6) { copy.breakfast = { items: [] }; copy.dinner = { items: [] }; }
      if (copy.lunch && copy.lunch.items && copy.lunch.items.length) copy.lunch.items[0] = copy.lunch.items[0] + ' · ' + isoDate.slice(5);
      return copy;
    });
    return { date: isoDate, dateLabel: dateHeading(isoDate), fetchedAt: base.fetchedAt, source: 'fixture', restaurants: restaurants };
  }

  global.BabdodukLabFixtures = { freeFeed: freeFeed, archive: archive, news: news, menu: menu, menuDay: menuDay };
})(window);
