// Loads the picker's dish catalog (data/foods/, docs/PICK.md). js/pick.js is the only caller.
// The old taste-preference recommender was removed on 2026-11-25: nothing had called it since the picker
// became one button (2026-11-04). Its saved key 'babdoduk-food-preferences' is simply no longer read.
(function (root) {
  var foods = [];
  var loadPromise = null;

  function loadCatalog() {
    if (loadPromise) return loadPromise;
    // The catalog changes only with a commit: 'no-cache' asks the server each time but takes a 304
    // (no body) when nothing changed, where 'no-store' downloaded all ~900 KB on every visit.
    loadPromise = fetch('data/foods/catalog.json', { cache: 'no-cache' })
      .then(function (res) {
        if (!res.ok) throw new Error('catalog missing');
        return res.json();
      })
      .then(function (payload) {
        return Promise.all((payload.packs || []).map(function (pack) {
          return fetch(pack.src, { cache: 'no-cache' }).then(function (res) {
            if (!res.ok) throw new Error('pack missing ' + pack.id);
            return res.json();
          });
        }));
      })
      .then(function (packs) {
        foods = [];
        packs.forEach(function (pack) {
          (pack.items || []).forEach(function (item) { foods.push(item); });
        });
        return foods;
      });
    return loadPromise;
  }

  root.BabdodukFoods = { load: loadCatalog };
})(window);
