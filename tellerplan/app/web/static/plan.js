// Plan beim Öffnen auf heute ausrichten: in der Spaltenansicht ganz links,
// in der Listenansicht ganz oben. Ein Sprungziel (#day-…) hat Vorrang.
(() => {
  const plan = document.querySelector("[data-plan]");
  if (!plan) return;
  const target = (location.hash && document.getElementById(location.hash.slice(1)))
    || plan.querySelector("[data-today]");
  if (!target) return;
  if (plan.classList.contains("plan-columns")) {
    plan.scrollLeft = target.offsetLeft - plan.offsetLeft;
  }
  if (!location.hash) {
    target.scrollIntoView({ block: "start" });
  }
})();
