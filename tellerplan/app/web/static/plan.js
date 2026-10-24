// Plan beim Öffnen auf heute ausrichten (oder auf ein Sprungziel #day-…):
// Spalten → waagerecht, sodass der Tag ganz links steht; die Seite bleibt oben.
// Liste   → senkrecht, sodass der Tag direkt unter der festen Kopfzeile steht.
(() => {
  const plan = document.querySelector("[data-plan]");
  if (!plan) return;
  const target = (location.hash && document.getElementById(location.hash.slice(1)))
    || plan.querySelector("[data-today]");
  if (!target) return;

  if (plan.classList.contains("plan-columns")) {
    plan.scrollLeft = target.offsetLeft - plan.offsetLeft;
    window.scrollTo({ top: 0 });
    return;
  }

  const header = document.querySelector("[data-plan-header]");
  const gap = 12;
  const offset = (header ? header.offsetHeight : 0) + gap;
  const top = target.getBoundingClientRect().top + window.scrollY - offset;
  window.scrollTo({ top: Math.max(0, top) });
})();
