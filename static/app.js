async function refresh() {
  const response = await fetch("/state", { cache: "no-store" });
  const state = await response.json();
  document.getElementById("self-character").textContent = state.self_character || "-";
  document.getElementById("opponent").textContent = state.opponent || "認識待ち";
  document.getElementById("confidence").textContent = (state.confidence ?? 0).toFixed(3);
  document.getElementById("status").textContent = state.status || "";

  const notes = document.getElementById("notes");
  notes.innerHTML = "";
  for (const note of state.notes || []) {
    const item = document.createElement("li");
    item.textContent = note;
    notes.appendChild(item);
  }
}

refresh();
setInterval(refresh, 700);
