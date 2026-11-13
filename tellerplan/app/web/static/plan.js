// Plan: Datum wählen verschiebt sofort; beim Öffnen ausrichten:
// 1. Kommt man aus dem Plan selbst zurück (Verschieben, Löschen, „Auf heute“), bleibt die
//    Ansicht, wo sie war (Befund K23): Die Position wird beim Abschicken gemerkt.
// 2. Sonst auf ein Sprungziel #day-… (z. B. nach „+ Einplanen“) oder auf heute:
//    Spalten → waagerecht, sodass der Tag ganz links steht; die Seite bleibt oben.
//    Liste   → senkrecht, sodass der Tag direkt unter der festen Kopfzeile steht.
(() => {
  const plan = document.querySelector("[data-plan]");
  if (!plan) return;

  const KEY = "tellerplan:plan-position";
  // Eine gemerkte Position gilt nur für das Neuladen direkt danach
  const MAX_AGE_MS = 60 * 1000;

  plan.addEventListener("submit", () => {
    try {
      sessionStorage.setItem(
        KEY,
        JSON.stringify({ left: plan.scrollLeft, top: window.scrollY, at: Date.now() }),
      );
    } catch {
      // Ohne Speicher (z. B. privates Fenster) springt der Plan wie früher
    }
  });

  const restore = () => {
    try {
      const raw = sessionStorage.getItem(KEY);
      sessionStorage.removeItem(KEY);
      if (!raw) return false;
      const position = JSON.parse(raw);
      if (Date.now() - position.at > MAX_AGE_MS) return false;
      plan.scrollLeft = position.left;
      window.scrollTo({ top: position.top });
      return true;
    } catch {
      return false;
    }
  };

  // Datum im Kalender gewählt → sofort verschieben, ohne Knopf. Wer das Datum tippt,
  // verschiebt erst beim Verlassen des Felds, sonst zählte schon der halbe Tag.
  for (const input of plan.querySelectorAll(".plan-move input[type=date]")) {
    const form = input.form;
    const button = form.querySelector("button[type=submit]");
    if (button) button.hidden = true;
    const initial = input.value;
    let typed = false;
    const send = () => {
      if (input.value && input.value !== initial && input.checkValidity()) form.requestSubmit();
    };
    input.addEventListener("keydown", () => { typed = true; });
    input.addEventListener("change", () => { if (!typed) send(); });
    input.addEventListener("blur", () => { if (typed) send(); });
  }

  if (!location.hash && restore()) return;

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
