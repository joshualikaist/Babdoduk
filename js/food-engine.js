(function (root) {
  var STORAGE_KEY = 'babdoduk-food-preferences';
  var TASTE_KEYS = ['spicy', 'sweet', 'salty', 'sour', 'umami', 'rich'];
  var DEFAULT_WEIGHTS = {
    taste: 35,
    craving: 20,
    context: 15,
    satietyHealth: 10,
    budgetDining: 10,
    popularityNovelty: 10
  };

  var catalog = null;
  var foods = [];
  var byId = {};
  var weights = DEFAULT_WEIGHTS;
  var loadPromise = null;

  function clamp(n, a, b) {
    return Math.max(a, Math.min(b, n));
  }

  function mealSlot(date) {
    var h = (date || new Date()).getHours();
    if (h >= 5 && h < 10) return 'breakfast';
    if (h >= 10 && h < 15) return 'lunch';
    if (h >= 15 && h < 17) return 'lunch';
    if (h >= 17 && h < 21) return 'dinner';
    return 'lateNight';
  }

  function emptyTaste() {
    return { spicy: 2.5, sweet: 2, salty: 2.5, sour: 2, umami: 3, rich: 2.5 };
  }

  function defaultPrefs() {
    return {
      version: 1,
      taste: emptyTaste(),
      likes: [],
      dislikes: [],
      eaten: [],
      hard: { diet: [], allergens: [] }
    };
  }

  function loadPrefs() {
    try {
      var raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return defaultPrefs();
      var parsed = JSON.parse(raw);
      var base = defaultPrefs();
      if (!parsed || parsed.version !== 1) return base;
      base.taste = parsed.taste || base.taste;
      base.likes = parsed.likes || [];
      base.dislikes = parsed.dislikes || [];
      base.eaten = parsed.eaten || [];
      base.hard = parsed.hard || base.hard;
      return base;
    } catch (err) {
      return defaultPrefs();
    }
  }

  function savePrefs(prefs) {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs));
    } catch (err) {}
    return prefs;
  }

  function mix(cur, target, amount) {
    if (cur == null) return target;
    return clamp(cur + (target - cur) * amount, 0, 5);
  }

  function applyFeedback(foodId, kind) {
    var food = byId[foodId];
    var prefs = loadPrefs();
    if (!food) return prefs;
    prefs.likes = prefs.likes.filter(function (id) { return id !== foodId; });
    prefs.dislikes = prefs.dislikes.filter(function (id) { return id !== foodId; });
    prefs.eaten = prefs.eaten.filter(function (id) { return id !== foodId; });
    var pull = kind === 'dislike' ? -0.12 : 0.18;
    TASTE_KEYS.forEach(function (key) {
      prefs.taste[key] = mix(prefs.taste[key], food.flavor[key], Math.abs(pull));
      if (kind === 'dislike') {
        prefs.taste[key] = mix(prefs.taste[key], 5 - food.flavor[key], 0.1);
      }
    });
    if (kind === 'like') prefs.likes.push(foodId);
    if (kind === 'dislike') prefs.dislikes.push(foodId);
    if (kind === 'eaten') {
      prefs.eaten.push(foodId);
      prefs.likes.push(foodId);
    }
    return savePrefs(prefs);
  }

  function loadCatalog() {
    if (loadPromise) return loadPromise;
    loadPromise = fetch('data/foods/catalog.json', { cache: 'no-store' })
      .then(function (res) {
        if (!res.ok) throw new Error('catalog missing');
        return res.json();
      })
      .then(function (payload) {
        catalog = payload;
        weights = payload.scoreWeights || DEFAULT_WEIGHTS;
        return Promise.all((payload.packs || []).map(function (pack) {
          return fetch(pack.src, { cache: 'no-store' }).then(function (res) {
            if (!res.ok) throw new Error('pack missing ' + pack.id);
            return res.json();
          });
        }));
      })
      .then(function (packs) {
        foods = [];
        byId = {};
        packs.forEach(function (pack) {
          (pack.items || []).forEach(function (item) {
            foods.push(item);
            byId[item.id] = item;
          });
        });
        return foods;
      });
    return loadPromise;
  }

  function hungerTarget(hunger) {
    if (hunger === 'light') return 1.5;
    if (hunger === 'heavy') return 4.7;
    if (hunger === 'mid') return 3.2;
    return null;
  }

  function kindMatch(food, kind) {
    if (!kind || kind === 'any') return 1;
    var carb = food.mainCarb || '';
    var dish = food.dishType || '';
    if (kind === 'rice') return carb === 'rice' || dish === 'rice-bowl' ? 1 : 0.05;
    if (kind === 'noodle') return carb.indexOf('noodle') !== -1 || carb === 'pasta' || dish === 'noodle' || dish === 'pasta' ? 1 : 0.05;
    if (kind === 'soup') return (food.texture && food.texture.soupy >= 3) || dish === 'soup' || dish === 'stew' || dish === 'hotpot' ? 1 : 0.05;
    if (kind === 'meat') return ['pork', 'beef', 'chicken', 'lamb', 'offal'].indexOf(food.mainProtein) !== -1 ? 1 : 0.05;
    if (kind === 'bread') return carb === 'wheat' || dish === 'bread' || dish === 'sandwich' || dish === 'pizza' || dish === 'wrap' ? 1 : 0.05;
    return 1;
  }

  function passesHard(food, answers, prefs) {
    if ((prefs.dislikes || []).indexOf(food.id) !== -1) return false;
    var hard = prefs.hard || {};
    var diet = hard.diet || [];
    var i;
    for (i = 0; i < diet.length; i += 1) {
      if ((food.diet || []).indexOf(diet[i]) === -1) return false;
    }
    var allergens = hard.allergens || [];
    for (i = 0; i < allergens.length; i += 1) {
      if ((food.allergens || []).indexOf(allergens[i]) !== -1) return false;
    }
    if (answers.budget === 'low' && food.priceLevel > 1) return false;
    if (answers.budget === 'mid' && food.priceLevel > 2) return false;
    if (answers.dining === 'delivery' && (food.diningMode || []).indexOf('delivery') === -1) return false;
    if (answers.dining === 'cook' && (food.diningMode || []).indexOf('homeCooking') === -1) return false;
    if (answers.dining === 'out' && (food.diningMode || []).indexOf('restaurant') === -1) return false;
    return true;
  }

  function tasteScore(food, prefs, answers) {
    var user = prefs.taste || emptyTaste();
    var target = {
      spicy: user.spicy,
      sweet: user.sweet,
      salty: user.salty,
      sour: user.sour,
      umami: user.umami,
      rich: user.rich
    };
    if (answers.craving === 'spicy') target.spicy = 4.6;
    if (answers.craving === 'hearty') target.rich = 4.2;
    if (answers.craving === 'light') {
      target.rich = 1.6;
      target.sweet = Math.min(target.sweet, 2.5);
    }
    var diff = 0;
    TASTE_KEYS.forEach(function (key) {
      diff += Math.abs((food.flavor[key] || 0) - target[key]);
    });
    return clamp(1 - diff / (TASTE_KEYS.length * 5), 0, 1);
  }

  function cravingScore(food, craving) {
    if (craving === 'spicy') return (food.flavor.spicy || 0) / 5;
    if (craving === 'hearty') return ((food.satiety || 0) + (food.flavor.rich || 0)) / 10;
    if (craving === 'light') return ((5 - (food.satiety || 0)) + (food.healthiness || 0)) / 10;
    if (craving === 'new') return (food.adventurousness || 0) / 5;
    return 0.5;
  }

  function contextScore(food, answers, slot) {
    var score = 0;
    if ((food.mealTime || []).indexOf(slot) !== -1) score += 0.55;
    else score += 0.12;
    var diningOcc = {
      solo: 'solo',
      friends: 'friends',
      date: 'date',
      delivery: 'solo',
      out: 'friends',
      cook: 'solo',
      any: null
    };
    var occ = diningOcc[answers.dining];
    if (!occ || answers.dining === 'any') score += 0.3;
    else if ((food.occasion || []).indexOf(occ) !== -1) score += 0.45;
    else score += 0.08;
    return clamp(score, 0, 1);
  }

  function satietyHealthScore(food, answers) {
    var target = hungerTarget(answers.hunger);
    var sat = 0.6;
    if (target != null) sat = 1 - Math.abs((food.satiety || 0) - target) / 5;
    var health = (food.healthiness || 0) / 5;
    if (answers.craving === 'light') return clamp(sat * 0.55 + health * 0.45, 0, 1);
    if (answers.craving === 'hearty') return clamp(sat * 0.85 + health * 0.15, 0, 1);
    return clamp(sat * 0.7 + health * 0.3, 0, 1);
  }

  function budgetDiningScore(food, answers) {
    var score = 0.5;
    if (answers.budget === 'low' && food.priceLevel === 1) score += 0.25;
    if (answers.budget === 'mid' && food.priceLevel === 2) score += 0.25;
    if (answers.budget === 'high' && food.priceLevel >= 2) score += 0.2;
    if (answers.dining === 'delivery' && (food.diningMode || []).indexOf('delivery') !== -1) score += 0.2;
    if (answers.dining === 'cook' && (food.diningMode || []).indexOf('homeCooking') !== -1) score += 0.2;
    if (answers.dining === 'out' && (food.diningMode || []).indexOf('restaurant') !== -1) score += 0.2;
    return clamp(score, 0, 1);
  }

  function popularityNoveltyScore(food, answers, prefs) {
    var pop = (food.popularity || 0) / 5;
    var neu = (food.adventurousness || 0) / 5;
    var liked = (prefs.likes || []).indexOf(food.id) !== -1 ? 0.12 : 0;
    if (answers.craving === 'new') return clamp(neu * 0.75 + (1 - pop) * 0.15 + liked, 0, 1);
    return clamp(pop * 0.8 + neu * 0.1 + liked, 0, 1);
  }

  function totalScore(food, answers, prefs, slot) {
    var w = weights;
    var parts = {
      taste: tasteScore(food, prefs, answers),
      craving: cravingScore(food, answers.craving),
      context: contextScore(food, answers, slot),
      satietyHealth: satietyHealthScore(food, answers),
      budgetDining: budgetDiningScore(food, answers),
      popularityNovelty: popularityNoveltyScore(food, answers, prefs)
    };
    parts.kind = kindMatch(food, answers.kind);
    var sum = 0;
    sum += parts.taste * w.taste;
    sum += parts.craving * w.craving;
    sum += parts.context * w.context;
    sum += parts.satietyHealth * w.satietyHealth;
    sum += parts.budgetDining * w.budgetDining;
    sum += parts.popularityNovelty * w.popularityNovelty;
    sum *= (0.35 + 0.65 * parts.kind);
    return { total: sum, parts: parts };
  }

  function reasonChips(food, answers) {
    var chips = [];
    var slot = mealSlot();
    if ((food.mealTime || []).indexOf(slot) !== -1) chips.push('now');
    if (answers.hunger === 'heavy' || answers.craving === 'hearty') {
      if (food.satiety >= 4) chips.push('hearty');
    }
    if (answers.hunger === 'light' || answers.craving === 'light') {
      if (food.satiety <= 2) chips.push('light');
    }
    if ((food.texture && food.texture.soupy >= 3) || food.dishType === 'soup' || food.dishType === 'stew') chips.push('soup');
    if (food.satiety >= 4 && chips.indexOf('hearty') === -1) chips.push('filling');
    var unique = [];
    chips.forEach(function (c) {
      if (unique.indexOf(c) === -1) unique.push(c);
    });
    return unique.slice(0, 4);
  }

  function diversify(ranked, limit) {
    var picked = [];
    var parents = {};
    var types = {};
    var groups = {};

    function tryAdd(row, strict) {
      var food = row.food;
      if (parents[food.parentId]) return false;
      var typeKey = food.cuisine + ':' + food.dishType;
      if (strict && types[typeKey]) return false;
      if (strict && groups[food.cuisineGroup] && groups[food.cuisineGroup] >= 2) return false;
      picked.push(row);
      parents[food.parentId] = true;
      types[typeKey] = true;
      groups[food.cuisineGroup] = (groups[food.cuisineGroup] || 0) + 1;
      return true;
    }

    ranked.forEach(function (row) {
      if (picked.length < limit) tryAdd(row, true);
    });
    ranked.forEach(function (row) {
      if (picked.length < limit) tryAdd(row, false);
    });
    ranked.forEach(function (row) {
      if (picked.length >= limit) return;
      var exists = picked.some(function (p) { return p.food.id === row.food.id; });
      if (!exists) picked.push(row);
    });
    return picked.slice(0, limit);
  }

  function recommend(answers, opts) {
    opts = opts || {};
    var prefs = loadPrefs();
    var slot = mealSlot();
    var skip = {};
    (opts.excludeIds || []).forEach(function (id) { skip[id] = true; });
    var ranked = [];
    foods.forEach(function (food) {
      if (skip[food.id]) return;
      if (!passesHard(food, answers, prefs)) return;
      var scored = totalScore(food, answers, prefs, slot);
      ranked.push({
        food: food,
        score: scored.total,
        parts: scored.parts,
        chips: reasonChips(food, answers)
      });
    });
    ranked.sort(function (a, b) { return b.score - a.score; });
    var offset = opts.offset || 0;
    var pool = ranked.slice(offset);
    var picks = diversify(pool, opts.limit || 3);
    if (picks.length < 3) picks = diversify(ranked, opts.limit || 3);
    return { picks: picks, ranked: ranked, count: foods.length };
  }

  function quickPick(opts) {
    opts = opts || {};
    var slot = mealSlot();
    var prefs = loadPrefs();
    var answers = opts.answers || {};
    var merged = {
      craving: answers.craving || 'any',
      kind: 'any',
      hunger: answers.hunger || 'any',
      dining: 'any',
      budget: 'any'
    };
    if (merged.hunger === 'any' && merged.craving === 'any') {
      merged.craving = slot === 'breakfast' ? 'light' : 'hearty';
      merged.hunger = 'mid';
    }
    var skip = {};
    (opts.excludeIds || []).forEach(function (id) { skip[id] = true; });
    var pool = foods.filter(function (food) {
      if (skip[food.id]) return false;
      if (!passesHard(food, merged, prefs)) return false;
      if ((food.mealTime || []).indexOf(slot) === -1) return false;
      if (merged.hunger === 'heavy' && (food.satiety || 0) < 3) return false;
      if (merged.hunger === 'light' && (food.satiety || 0) > 3) return false;
      return true;
    });
    if (!pool.length) {
      pool = foods.filter(function (food) {
        if (skip[food.id]) return false;
        return passesHard(food, merged, prefs);
      });
    }
    pool.sort(function (a, b) { return (b.popularity || 0) - (a.popularity || 0); });
    var pick;
    if (Math.random() < 0.55) {
      var top = pool.slice(0, Math.min(pool.length, 48));
      pick = top[Math.floor(Math.random() * top.length)];
    } else {
      pick = pool[Math.floor(Math.random() * pool.length)];
    }
    pick = pick || pool[0];
    var rolling = [];
    var seenRoll = {};
    if (pick) {
      rolling.push(pick);
      seenRoll[pick.id] = true;
    }
    var i;
    var mix = pool.slice();
    for (i = mix.length - 1; i > 0; i -= 1) {
      var j = Math.floor(Math.random() * (i + 1));
      var tmp = mix[i];
      mix[i] = mix[j];
      mix[j] = tmp;
    }
    for (i = 0; i < mix.length && rolling.length < 16; i += 1) {
      if (seenRoll[mix[i].id]) continue;
      seenRoll[mix[i].id] = true;
      rolling.push(mix[i]);
    }
    return { food: pick, rolling: rolling, answers: merged, slot: slot };
  }

  root.BabdodukFoods = {
    load: loadCatalog,
    recommend: recommend,
    quickPick: quickPick,
    mealSlot: mealSlot,
    prefs: { load: loadPrefs, save: savePrefs, feedback: applyFeedback },
    get: function (id) { return byId[id]; },
    all: function () { return foods; },
    count: function () { return foods.length; },
    catalogCount: function () { return catalog && catalog.count ? catalog.count : foods.length; }
  };
})(window);
