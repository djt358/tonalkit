// Small DOM helpers: screens, copy, the level meter and the tap-to-answer questions.

export const $ = (id) => document.getElementById(id);

let current = "loading";
export const currentScreen = () => current;

/** Shows `screen-<name>` and hides the others. */
export function show(name) {
  for (const section of document.querySelectorAll("section.screen")) section.hidden = section.id !== `screen-${name}`;
  current = name;
  window.scrollTo(0, 0);
}

/** Fills every [data-copy] element from the copy. */
export function applyCopy(t) {
  for (const el of document.querySelectorAll("[data-copy]")) el.textContent = t(el.dataset.copy);
}

/** A tap handler that ignores taps while its previous run is still going (no double submits). */
export function onTap(id, handler) {
  const el = $(id);
  el.addEventListener("click", async (event) => {
    if (el.dataset.busy) return;
    el.dataset.busy = "1";
    try {
      await handler(event);
    } finally {
      delete el.dataset.busy;
    }
  });
}

export function setText(el, text) {
  el.textContent = text;
  el.hidden = !text;
}

const METER_FLOOR_DB = -60;

/** Moves every level meter: -60 dBFS (empty) to 0 dBFS (full). */
export function setMeter(db) {
  const pct = Math.max(0, Math.min(100, ((db - METER_FLOOR_DB) / -METER_FLOOR_DB) * 100));
  for (const fill of document.querySelectorAll(".meter-fill")) fill.style.transform = `scaleX(${pct / 100})`;
}

const mark = (buttons, value) => {
  for (const b of buttons) b.setAttribute("aria-checked", String(b.dataset.value === value));
};

/** Shows `value` as question `name`'s answer when the app picks it (not a tap). */
export const selectChoice = (name, value) => mark(document.querySelectorAll(`#q-${name} .choice`), value);

/**
 * A question answered by tapping one of its options (radio semantics, big targets).
 * @param {{name: string, label: string, options: {value: string, label: string}[], selected: string,
 *          onPick: (value: string) => void}} q
 */
export function choiceGroup({ name, label, options, selected, onPick }) {
  const group = document.createElement("fieldset");
  group.className = "choices";
  group.id = `q-${name}`;
  const legend = document.createElement("legend");
  legend.textContent = label;
  group.append(legend);
  const buttons = options.map(({ value, label: text }) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "choice";
    b.dataset.value = value;
    b.setAttribute("role", "radio");
    b.textContent = text;
    b.addEventListener("click", () => {
      mark(buttons, value);
      onPick(value);
    });
    return b;
  });
  mark(buttons, selected);
  const list = document.createElement("div");
  list.setAttribute("role", "radiogroup");
  list.setAttribute("aria-label", label);
  list.append(...buttons);
  group.append(list);
  return group;
}
