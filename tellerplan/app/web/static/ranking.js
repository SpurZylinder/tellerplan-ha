// Rezept-Ranking wie im Widget „Protein-Ranking Fürth“:
// Score = w·P̂ + (1−w)·(1−K̂), P̂ und K̂ auf Min/Max der gezeigten Rezepte normiert.
(() => {
  const controls = document.querySelector("[data-ranking-controls]");
  const list = document.querySelector("[data-ranking-list]");
  if (!controls || !list) return;

  const slider = controls.querySelector("[data-weight]");
  const search = controls.querySelector("[data-search]");
  const categoryChips = [...controls.querySelectorAll("[data-category]")];
  const favoritesChip = controls.querySelector("[data-favorites]");
  const items = [...list.children];

  let category = "";
  let favoritesOnly = false;

  const normalize = (value, min, max) => (max > min ? (value - min) / (max - min) : 0.5);

  const isFavorite = (item) =>
    item.querySelector(".star")?.getAttribute("aria-pressed") === "true";

  function isVisible(item) {
    const query = search.value.trim().toLowerCase();
    if (category && item.dataset.category !== category) return false;
    if (favoritesOnly && !isFavorite(item)) return false;
    return !query || item.dataset.title.includes(query);
  }

  function update() {
    const weight = Number(slider.value) / 100;
    const visible = items.filter(isVisible);
    const rankable = visible.filter((item) => item.dataset.rankable === "true");
    const proteins = rankable.map((item) => Number(item.dataset.protein));
    const kcals = rankable.map((item) => Number(item.dataset.kcal));
    const [pMin, pMax] = [Math.min(...proteins), Math.max(...proteins)];
    const [kMin, kMax] = [Math.min(...kcals), Math.max(...kcals)];

    const scored = visible.map((item) => {
      if (item.dataset.rankable !== "true") return { item, score: -1 };
      const p = normalize(Number(item.dataset.protein), pMin, pMax);
      const k = normalize(Number(item.dataset.kcal), kMin, kMax);
      return { item, score: weight * p + (1 - weight) * (1 - k) };
    });
    scored.sort((a, b) => b.score - a.score);

    items.forEach((item) => (item.hidden = true));
    scored.forEach(({ item, score }, index) => {
      item.hidden = false;
      item.querySelector("[data-rank]").textContent = index + 1;
      item.querySelector("[data-score]").textContent = score < 0 ? "–" : Math.round(score * 100);
      item.querySelector("[data-bar]").style.width = `${Math.max(score, 0) * 100}%`;
      list.appendChild(item);
    });
  }

  categoryChips.forEach((chip) =>
    chip.addEventListener("click", () => {
      category = chip.dataset.category;
      categoryChips.forEach((c) => c.setAttribute("aria-pressed", String(c === chip)));
      update();
    }),
  );
  favoritesChip.addEventListener("click", () => {
    favoritesOnly = !favoritesOnly;
    favoritesChip.setAttribute("aria-pressed", String(favoritesOnly));
    update();
  });
  slider.addEventListener("input", update);
  search.addEventListener("input", update);
  document.body.addEventListener("htmx:afterSwap", () => favoritesOnly && update());

  update();
})();
