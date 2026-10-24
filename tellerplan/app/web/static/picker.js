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
