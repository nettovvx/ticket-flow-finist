document.addEventListener("submit", (event) => {
  const form = event.target;
  if (!(form instanceof HTMLFormElement)) {
    return;
  }
  if (form.action.includes("/hide")) {
    const confirmed = window.confirm("Скрыть документ из оперативного списка?");
    if (!confirmed) {
      event.preventDefault();
    }
  }
});

