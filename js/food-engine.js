(function (root) {
  var foods = [];
  var loadPromise = null;

  function loadCatalog() {
    if (loadPromise) return loadPromise;
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
