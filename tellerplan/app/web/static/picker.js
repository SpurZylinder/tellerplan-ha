// Auswahllisten (.picker) beim Tippen filtern, ohne Serveranfrage,
// und eine vorausgewählte Option ins Bild scrollen.
document.querySelectorAll("[data-filter-picker]").forEach((input) => {
  const labels = input.parentElement.querySelectorAll(".picker label[data-title]");
  input.addEventListener("input", () => {
    const query = input.value.trim().toLowerCase();
    labels.forEach((label) => (label.hidden = query !== "" && !label.dataset.title.includes(query)));
  });
});
document.querySelector(".picker input:checked")?.scrollIntoView({ block: "center" });

// Andere Mahlzeit gewählt: Seite neu laden, damit Vorfilter und Vorschlag von gestern passen.
document.querySelectorAll("[data-reload-meal]").forEach((select) => {
  select.addEventListener("change", () => {
    location.assign(`${select.dataset.reloadMeal}&meal=${encodeURIComponent(select.value)}`);
  });
});

// Vorschlag von gestern gewählt: dessen Portionen übernehmen.
document.querySelectorAll(".picker input[data-servings]").forEach((radio) => {
  radio.addEventListener("change", () => {
    const servings = radio.form?.elements.namedItem("servings");
    if (servings) servings.value = radio.dataset.servings;
  });
});
