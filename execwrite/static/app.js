"use strict";

const MAX_WORDS = 2000;
const GENERIC_ERROR = "La reformulation a échoué. Réessayez.";
const NUMBER_FORMAT = new Intl.NumberFormat("fr-FR");

const draft = document.getElementById("draft");
const wordCount = document.getElementById("word-count");
const submit = document.getElementById("submit");
const resultBox = document.getElementById("result");
const empty = document.getElementById("empty");
const output = document.getElementById("output");
const status = document.getElementById("status");
const copy = document.getElementById("copy");
const adjustmentButtons = [...document.querySelectorAll("[data-adjustment]")];

let busy = false;
let result = "";
// Brouillon à l'origine du résultat affiché : les ajustements repartent de lui,
// même si la zone de saisie a été modifiée entre-temps.
let sourceDraft = "";

function countWords(text) {
  return (text.trim().match(/\S+/g) || []).length;
}

function setStatus(message, isError = false) {
  status.textContent = message;
  status.classList.toggle("is-error", isError);
}

function renderResult(text) {
  result = text;
  output.textContent = text;
}

function refreshControls() {
  const words = countWords(draft.value);
  const isOver = words > MAX_WORDS;
  wordCount.textContent = `${NUMBER_FORMAT.format(words)} / ${NUMBER_FORMAT.format(MAX_WORDS)} mots`;
  wordCount.classList.toggle("is-over", isOver);

  submit.disabled = busy || words === 0 || isOver;
  submit.textContent = busy ? "Reformulation…" : "Reformuler";

  const hasResult = Boolean(result);
  copy.disabled = busy || !hasResult;
  adjustmentButtons.forEach((button) => {
    button.disabled = busy || !hasResult;
  });

  resultBox.setAttribute("aria-busy", String(busy));
  empty.hidden = hasResult || busy;
}

async function readError(response) {
  try {
    const { detail } = await response.json();
    return typeof detail === "string" ? detail : GENERIC_ERROR;
  } catch {
    return GENERIC_ERROR;
  }
}

async function streamRewrite(payload, onDelta) {
  const response = await fetch("/api/rewrite", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(await readError(response));
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finished = false;

  const handleLine = (line) => {
    const event = JSON.parse(line);
    if (event.type === "delta") onDelta(event.text);
    if (event.type === "error") throw new Error(event.message);
    if (event.type === "done") finished = true;
  };

  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop();
    lines.filter(Boolean).forEach(handleLine);
  }

  if (!finished) throw new Error(GENERIC_ERROR);
}

async function run(adjustment = null) {
  if (busy) return;

  const text = adjustment ? sourceDraft : draft.value;
  const previous = adjustment ? result : null;
  const before = { result, sourceDraft };
  const startedAt = performance.now();
  let accumulated = "";

  busy = true;
  renderResult("");
  setStatus("");
  refreshControls();

  try {
    await streamRewrite({ text, adjustment, previous }, (delta) => {
      accumulated += delta;
      renderResult(accumulated);
    });
    sourceDraft = text;
    const seconds = ((performance.now() - startedAt) / 1000).toFixed(1).replace(".", ",");
    setStatus(`Généré en ${seconds} s`);
  } catch (error) {
    // Un texte interrompu ne doit pas pouvoir être copié et envoyé.
    renderResult(before.result);
    sourceDraft = before.sourceDraft;
    const isOwnMessage = error instanceof Error && !(error instanceof TypeError) && !(error instanceof SyntaxError);
    setStatus(isOwnMessage ? error.message : GENERIC_ERROR, true);
  } finally {
    busy = false;
    refreshControls();
  }
}

async function writeClipboard(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    // Repli pour les contextes où l'API du presse-papiers est indisponible.
    const helper = document.createElement("textarea");
    helper.value = text;
    helper.setAttribute("readonly", "");
    helper.style.position = "fixed";
    helper.style.opacity = "0";
    document.body.append(helper);
    helper.select();
    const copied = document.execCommand("copy");
    helper.remove();
    return copied;
  }
}

let copyLabelTimer;

copy.addEventListener("click", async () => {
  if (await writeClipboard(result)) {
    copy.textContent = "Copié";
    clearTimeout(copyLabelTimer);
    copyLabelTimer = setTimeout(() => {
      copy.textContent = "Copier";
    }, 1800);
  } else {
    setStatus("La copie a échoué. Sélectionnez le texte manuellement.", true);
  }
});

draft.addEventListener("input", refreshControls);
draft.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && (event.ctrlKey || event.metaKey) && !submit.disabled) {
    event.preventDefault();
    run();
  }
});
submit.addEventListener("click", () => run());
adjustmentButtons.forEach((button) => {
  button.addEventListener("click", () => run(button.dataset.adjustment));
});

refreshControls();
