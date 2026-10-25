// Einkaufsliste als Text kopieren. Über HTTP (lokal am iPhone) fehlt die
// Zwischenablage-API, dann bleibt der Text markiert und lässt sich von Hand kopieren.
(() => {
  const button = document.querySelector("[data-copy]");
  const source = document.querySelector("[data-copy-source]");
  if (!button || !source) return;

  button.addEventListener("click", async () => {
    source.select();
    try {
      await navigator.clipboard.writeText(source.value);
      button.textContent = "Kopiert ✓";
    } catch {
      button.textContent = "Markiert – bitte kopieren";
    }
  });
})();
