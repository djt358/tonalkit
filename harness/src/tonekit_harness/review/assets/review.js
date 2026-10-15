"use strict";
// tkh review: listen to each clip and record what was said. Keyboard first; decisions stay in
// this browser (localStorage, per corpus) until exported as relabels-<corpus>.json.
(() => {
  const DATA = JSON.parse(document.getElementById("review-data").textContent);
  const KEY = `tonekit-review:${DATA.corpus}`;
  const TONES = DATA.tones;
  const CLIPS = DATA.clips;
  const SESSION_ID = /^([A-HJ-NP-Z2-9]{6})-/;
  const SESSIONS = new Set(DATA.sessions);
  const VERDICTS = new Set(["as_card", "heard", "unclear", "exclude"]);
  const SAID = { as_card: "as the card says", heard: "heard", unclear: "unclear", exclude: "excluded: bad audio" };

  const $ = (id) => document.getElementById(id);
  const el = (tag, cls, text) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined && text !== null) e.textContent = text;
    return e;
  };
  const same = (a, b) => a.length === b.length && a.every((x, i) => x === b[i]);

  // ---- what this browser keeps -------------------------------------------------------------
  let storageOk = true;

  function cleanDecision(d) {
    if (!d || typeof d !== "object" || !VERDICTS.has(d.verdict) || typeof d.decided_at !== "string") return null;
    const tones = Array.isArray(d.tones) ? d.tones.map(String) : null;
    if (d.verdict === "heard" && !tones) return null;
    return { verdict: d.verdict, tones: d.verdict === "heard" ? tones : null, decided_at: d.decided_at };
  }

  function loadStore() {
    let text = null;
    try {
      text = window.localStorage.getItem(KEY);
    } catch (e) {
      storageOk = false; // a browser that keeps nothing for pages opened from disk
    }
    let saved = null;
    try {
      saved = JSON.parse(text || "null");
    } catch (e) {
      saved = null; // damaged: start again
    }
    const store = { who: "", focus: null, decisions: {} };
    if (saved && typeof saved === "object") {
      store.who = typeof saved.who === "string" ? saved.who : "";
      store.focus = typeof saved.focus === "string" ? saved.focus : null;
      for (const [id, d] of Object.entries(saved.decisions || {})) {
        const m = SESSION_ID.exec(id);
        if (m && !SESSIONS.has(m[1])) continue; // a purged session: forget what was decided about it
        const clean = cleanDecision(d);
        if (clean) store.decisions[id] = clean;
      }
    }
    for (const c of CLIPS) {
      // what an earlier `tkh relabel` applied, when this browser has nothing newer
      if (!store.decisions[c.id] && c.applied) store.decisions[c.id] = cleanDecision(c.applied);
    }
    return store;
  }

  const store = loadStore();

  function persist() {
    try {
      window.localStorage.setItem(KEY, JSON.stringify(store));
    } catch (e) {
      storageOk = false;
    }
  }

  function save() {
    persist();
    paintSummary();
  }

  // ---- decisions ---------------------------------------------------------------------------
  const decisionOf = (i) => store.decisions[CLIPS[i].id] || null;

  function selectedTones(i) {
    const d = decisionOf(i);
    return d && d.verdict === "heard" ? d.tones.slice() : CLIPS[i].tones.slice();
  }

  function record(i, verdict, tones) {
    const c = CLIPS[i];
    if (verdict === "heard" && same(tones, c.tones)) verdict = "as_card";
    store.decisions[c.id] = { verdict, tones: verdict === "heard" ? tones : null, decided_at: new Date().toISOString() };
    store.focus = c.id;
    save();
    paint(i);
  }

  function setTone(i, s, tone) {
    const tones = selectedTones(i);
    tones[s] = tone;
    record(i, "heard", tones);
  }

  function undecide(i) {
    delete store.decisions[CLIPS[i].id];
    save();
    paint(i);
  }

  // ---- the page ----------------------------------------------------------------------------
  const rows = [];
  let fi = 0; // focused clip
  let si = 0; // focused syllable

  function labelText(c) {
    if (c.label === "correct") return ["label", "correct reading"];
    if (c.label !== "tone_error") return ["label", `label: ${c.label}`];
    const parts = c.tones
      .map((t, k) => (t === c.intended[k] ? null : `${c.syllables[k].forms[t] || t} (tone ${t}) where the word has ${c.syllables[k].forms[c.intended[k]] || c.intended[k]} (tone ${c.intended[k]})`))
      .filter(Boolean);
    const twin = c.twin ? `; its correct card: ${c.twin}` : "";
    return ["label error", `deliberate error: ${parts.join(", ")}${twin}`];
  }

  function nowText(now) {
    if (!now) return null;
    if (now.excluded) return "In the manifest now: excluded (bad audio).";
    let t = `In the manifest now: ${now.label} ${now.tones.join(" ")}`;
    if (now.left_pair) t += ", out of its pair";
    if (now.needs_listen) t += ", flagged for another listen";
    return `${t}.`;
  }

  function scorerText(c, s, k) {
    if (!DATA.results || c.group === "not_graded") return ["scorer", "scorer: not graded"];
    if (s.note === "not measured") return ["scorer", "scorer: not measured"];
    const heard = s.heard ? `heard ${s.heard}` : "unsure";
    const p = s.p === null ? "" : ` · p(tone ${c.intended[k]}) ${s.p.toFixed(2)}`;
    const note = s.note ? ` · ${s.note}` : "";
    const disagree = s.heard && s.heard !== c.tones[k];
    return [disagree ? "scorer disagree" : "scorer", `scorer: ${heard}${p}${note}`];
  }

  function build(c, i) {
    const box = el("section", "clip");
    box.id = `clip-${i}`;
    const head = el("div", "head");
    head.append(
      el("span", "n", `${i + 1}/${CLIPS.length}`),
      el("span", `group ${c.group}`, c.group_name),
      el("span", null, `${c.speaker}${c.about ? ` (${c.about})` : ""}`),
      el("span", null, `card ${c.card || c.id} · ${c.set}`),
    );
    const verdict = el("span", "verdict");
    head.append(verdict);

    const text = el("div", "text");
    const hanzi = el("span", "hanzi");
    const read = c.script === "traditional" ? c.traditional : c.text;
    const other = c.script === "traditional" ? c.text : c.traditional;
    hanzi.append(el("span", "read", read));
    if (other && other !== read) hanzi.append(" ", el("span", "other", other));
    const [lcls, ltext] = labelText(c);
    text.append(hanzi, el("span", "pinyin", c.pinyin), el("span", lcls, ltext));
    const seen = [];
    if (c.script) seen.push(`read in ${c.script}`);
    if (c.pinyin_shown === false) seen.push("no pinyin shown");
    if (seen.length) text.append(el("span", "note", seen.join(", ")));
    box.append(head, text);
    if (c.note) box.append(el("p", "note", `Card note: ${c.note}`));
    const now = nowText(c.now);
    if (now) box.append(el("p", "now", now));

    const row = el("div", "row");
    let audio = null;
    if (c.audio) {
      audio = el("audio");
      audio.controls = true;
      audio.preload = "none";
      audio.src = c.audio;
      audio.tabIndex = -1;
      audio.addEventListener("play", () => {
        for (const r of rows) if (r.audio && r.audio !== audio) r.audio.pause();
      });
      audio.addEventListener("focus", () => audio.blur());
      row.append(audio);
    } else {
      row.append(el("span", "note", "audio missing"));
    }
    const syls = el("div", "syls");
    const sylEls = c.syllables.map((s, k) => {
      const box2 = el("div", "syl");
      const top = el("div", "top");
      if (s.hanzi) top.append(el("span", "han", s.hanzi));
      top.append(el("span", null, `card: ${s.forms[c.tones[k]] || c.tones[k]}`));
      const tones = el("div", "tones");
      const buttons = {};
      for (const t of TONES) {
        const b = el("button", t === c.tones[k] ? "card" : null, `${t} ${s.forms[t] || ""}`.trim());
        b.type = "button";
        b.title = `tone ${t}`;
        b.addEventListener("click", (ev) => {
          ev.currentTarget.blur();
          focusClip(i, false);
          si = k;
          setTone(i, k, t);
        });
        buttons[t] = b;
        tones.append(b);
      }
      const [scls, stext] = scorerText(c, s, k);
      box2.append(top, tones, el("div", scls, stext));
      syls.append(box2);
      return { box: box2, buttons };
    });
    const acts = el("div", "acts");
    const act = (label, fn) => {
      const b = el("button", null, label);
      b.type = "button";
      b.addEventListener("click", (ev) => {
        ev.currentTarget.blur();
        focusClip(i, false);
        fn();
      });
      acts.append(b);
    };
    act("As the card says (Enter)", () => record(i, "as_card", c.tones.slice()));
    act("Unclear (U)", () => record(i, "unclear", null));
    act("Bad audio, exclude (X)", () => record(i, "exclude", null));
    row.append(syls, acts);
    box.append(row);
    box.addEventListener("click", () => focusClip(i, false));
    return { box, verdict, audio, sylEls };
  }

  function paint(i) {
    const c = CLIPS[i];
    const r = rows[i];
    const d = decisionOf(i);
    r.box.className = `clip${d ? ` ${d.verdict}` : ""}${i === fi ? " focused" : ""}`;
    const tones = selectedTones(i);
    let said = "undecided";
    if (d) {
      said = d.verdict === "heard" ? `heard ${d.tones.join(" ")}` : SAID[d.verdict];
      const a = c.applied;
      if (a && a.verdict === d.verdict && a.decided_at === d.decided_at) said += " (applied)";
    }
    r.verdict.textContent = said;
    r.verdict.className = `verdict${d ? ` ${d.verdict}` : ""}`;
    r.sylEls.forEach((s, k) => {
      s.box.className = `syl${i === fi && k === si ? " focused" : ""}`;
      for (const [t, b] of Object.entries(s.buttons)) {
        const sel = t === tones[k] && (!d || d.verdict === "as_card" || d.verdict === "heard");
        b.className = [t === c.tones[k] ? "card" : "", sel ? "sel" : "", sel && t !== c.tones[k] ? "changed" : ""]
          .filter(Boolean)
          .join(" ");
      }
    });
  }

  function paintSummary() {
    const decided = CLIPS.filter((c) => store.decisions[c.id]).length;
    const n = (g) => CLIPS.filter((c) => c.group === g).length;
    const groups = [n("twin"), n("disagrees"), n("unsure"), n("not_graded")];
    const filters = [...DATA.filters.speakers, ...DATA.filters.sets];
    let s = `${CLIPS.length} clips${filters.length ? ` (only ${filters.join(", ")})` : ""} · ${decided} decided`;
    if (DATA.results) {
      s += ` · the scorer hears the twin card's reading in ${groups[0]}, otherwise disagrees with ${groups[1]}, is unsure of ${groups[2]}`;
      if (groups[3]) s += `, never graded ${groups[3]}`;
      s += ` · scorer: ${DATA.results.file} (register from ${DATA.results.register_from})`;
    } else {
      s += " · no scorer view: run tkh eval with --results first";
    }
    $("summary").textContent = s;
    if (!storageOk) setStatus("This browser is not keeping decisions for a page opened from disk: export before you close it.", true);
  }

  function setStatus(text, warn) {
    const s = $("status");
    s.textContent = text;
    s.className = warn ? "warn" : "";
  }

  // ---- moving and playing ------------------------------------------------------------------
  function focusClip(i, play) {
    if (i < 0 || i >= CLIPS.length) return;
    const before = fi;
    if (i !== before && rows[before].audio) rows[before].audio.pause();
    fi = i;
    if (i !== before) si = 0;
    store.focus = CLIPS[i].id;
    persist();
    paint(before);
    paint(i);
    if (i !== before) rows[i].box.scrollIntoView({ block: "center" });
    if (play && $("autoplay").checked) start(i);
  }

  function start(i) {
    const a = rows[i].audio;
    if (!a) return;
    a.currentTime = 0;
    a.play().catch(() => setStatus("Could not play this clip.", true));
  }

  function toggle(i) {
    const a = rows[i].audio;
    if (!a) return;
    if (a.paused) {
      if (a.ended) a.currentTime = 0;
      a.play().catch(() => setStatus("Could not play this clip.", true));
    } else {
      a.pause();
    }
  }

  function moveSyllable(step) {
    const n = CLIPS[fi].syllables.length;
    si = Math.max(0, Math.min(n - 1, si + step));
    paint(fi);
  }

  function next(play) {
    focusClip(Math.min(fi + 1, CLIPS.length - 1), play);
  }

  document.addEventListener("keydown", (ev) => {
    const t = ev.target;
    if (t instanceof HTMLInputElement || t instanceof HTMLTextAreaElement) return;
    if (ev.metaKey || ev.ctrlKey || ev.altKey || !CLIPS.length) return;
    const k = ev.key;
    if (k === " ") toggle(fi);
    else if (TONES.includes(k)) {
      setTone(fi, si, k);
      moveSyllable(+1);
    } else if (k === "ArrowLeft") moveSyllable(-1);
    else if (k === "ArrowRight") moveSyllable(+1);
    else if (k === "ArrowUp") focusClip(fi - 1, false);
    else if (k === "ArrowDown") focusClip(fi + 1, true);
    else if (k === "Enter") {
      record(fi, "heard", selectedTones(fi));
      next(true);
    } else if (k === "u" || k === "U") {
      record(fi, "unclear", null);
      next(true);
    } else if (k === "x" || k === "X") {
      record(fi, "exclude", null);
      next(true);
    } else if (k === "Backspace" || k === "Delete") undecide(fi);
    else if (k === "r" || k === "R") start(fi);
    else return;
    ev.preventDefault();
  });

  // ---- export --------------------------------------------------------------------------------
  function exportDecisions() {
    const who = $("who").value.trim();
    if (!who) {
      setStatus("Type your initials first.", true);
      $("who").focus();
      return;
    }
    const decisions = Object.keys(store.decisions)
      .sort()
      .map((id) => ({ clip: id, ...store.decisions[id] }));
    const doc = { schema: "tonekit.relabels.v1", corpus: DATA.corpus, who, exported_at: new Date().toISOString(), decisions };
    const url = URL.createObjectURL(new Blob([`${JSON.stringify(doc, null, 1)}\n`], { type: "application/json" }));
    const a = el("a");
    a.href = url;
    a.download = `relabels-${DATA.corpus}.json`;
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
    setStatus(`Exported ${decisions.length} decisions to relabels-${DATA.corpus}.json; now run tkh relabel on it.`, false);
  }

  // ---- start -----------------------------------------------------------------------------------
  const main = $("clips");
  CLIPS.forEach((c, i) => {
    const r = build(c, i);
    rows.push(r);
    main.append(r.box);
  });
  $("who").value = store.who;
  $("who").addEventListener("input", () => {
    store.who = $("who").value;
    save();
  });
  $("export").addEventListener("click", (ev) => {
    ev.currentTarget.blur();
    exportDecisions();
  });
  persist(); // without the decisions about purged sessions that loadStore dropped
  const resume = CLIPS.findIndex((c) => c.id === store.focus);
  fi = resume >= 0 ? resume : 0;
  CLIPS.forEach((_, i) => paint(i));
  paintSummary();
  if (CLIPS.length && fi > 0) rows[fi].box.scrollIntoView({ block: "center" });
})();
