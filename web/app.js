/* Safar — frontend logic. Talks to the stdlib server in ../server.py. */
(() => {
  "use strict";

  // ----- session (URL ?sid= wins, so a trip can be shared / linked) -----
  const SID_KEY = "safar.sid";
  const urlSid = new URLSearchParams(location.search).get("sid");
  let sid = urlSid || localStorage.getItem(SID_KEY);
  if (!sid) { sid = "s" + Math.random().toString(36).slice(2, 10); }
  localStorage.setItem(SID_KEY, sid);

  const REDUCED = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  const $ = (s, r = document) => r.querySelector(s);
  const el = (tag, cls, html) => { const n = document.createElement(tag); if (cls) n.className = cls; if (html != null) n.innerHTML = html; return n; };

  const IATA = { delhi:"DEL","new delhi":"DEL", mumbai:"BOM", bombay:"BOM", bangalore:"BLR", bengaluru:"BLR",
    chennai:"MAA", kolkata:"CCU", hyderabad:"HYD", goa:"GOI", jaipur:"JAI", ahmedabad:"AMD", pune:"PNQ",
    kochi:"COK", lucknow:"LKO", varanasi:"VNS", udaipur:"UDR", agra:"AGR", amritsar:"ATQ", srinagar:"SXR" };
  const iata = s => { s = (s||"").trim().toLowerCase(); if (s.length===3 && /^[a-z]+$/.test(s)) return s.toUpperCase(); return IATA[s] || s.slice(0,3).toUpperCase(); };

  const MON = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  const DOW = ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"];
  const parseDate = s => { const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s||""); return m ? new Date(+m[1], +m[2]-1, +m[3]) : null; };
  const fmtDateShort = s => { const d = parseDate(s); return d ? `${String(d.getDate()).padStart(2,"0")} ${MON[d.getMonth()]}`.toUpperCase() : ""; };
  const fmtDateLong  = s => { const d = parseDate(s); return d ? `${DOW[d.getDay()]} ${d.getDate()} ${MON[d.getMonth()]}` : s; };
  const rupee = n => "₹" + Number(n||0).toLocaleString("en-IN");
  const esc = s => (s||"").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));

  // ----- icons (monoline) -----
  const ICON = {
    plane: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M2 13l9-2 5-9 2 1-2 9 6 3v2l-7-1-3 5h-2l1-6-5-1-2 3H2z"/></svg>',
    route: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7h11a3 3 0 0 1 0 6H8a3 3 0 0 0 0 6h13"/><path d="M18 4l3 3-3 3"/></svg>',
    bed:   '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 18V8m0 6h18m0 4V11a3 3 0 0 0-3-3H9"/><circle cx="6.5" cy="11.5" r="1.5"/></svg>',
    compass:'<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M15.5 8.5l-2 5-5 2 2-5z"/></svg>',
    fork:  '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M5 3v6a2 2 0 0 0 4 0V3M7 11v10M17 3c-1.5 1-2 3-2 5s.5 3 2 3v10"/></svg>'
  };
  const eventKind = k => {
    if (k.startsWith("FLIGHT")) return ["plane","move"];
    if (k.startsWith("TRANSIT")) return ["route","move"];
    if (k === "HOTEL_CHECKIN") return ["bed","stay"];
    if (k === "MEAL") return ["fork",""];
    return ["compass",""];
  };

  // ----- markdown-lite (escape first, then a safe subset) -----
  function md(text) {
    const lines = esc(text).split("\n");
    let out = "", inList = false;
    for (let line of lines) {
      line = line.replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/(^|[^*])\*(?!\s)(.+?)\*/g, "$1<i>$2</i>");
      if (/^\s*-\s+/.test(line)) {
        if (!inList) { out += "<ul>"; inList = true; }
        out += "<li>" + line.replace(/^\s*-\s+/, "") + "</li>";
      } else {
        if (inList) { out += "</ul>"; inList = false; }
        out += line.trim() ? line + "<br>" : "<br>";
      }
    }
    if (inList) out += "</ul>";
    return out.replace(/(<br>)+$/,"");
  }

  // ----- flap board -----
  function buildFlaps() {
    document.querySelectorAll(".flaps").forEach(f => {
      const n = +f.dataset.cells, pad = f.dataset.pad || " ";
      f.innerHTML = "";
      for (let i=0;i<n;i++){ const c = el("span","flap", pad); f._pad = pad; f.appendChild(c); }
    });
  }
  function setField(field, text) {
    const group = document.querySelector(`.flapgroup[data-field="${field}"] .flaps`);
    if (!group) return;
    const cells = group.children, n = cells.length, pad = group.dataset.pad || " ";
    text = (text || "").toUpperCase().slice(0, n);
    for (let i=0;i<n;i++){
      const want = text[i] || pad, cell = cells[i];
      if (cell.textContent === want) continue;
      cell.textContent = want;
      if (!REDUCED) { cell.classList.remove("flap--flip"); void cell.offsetWidth;
        cell.style.animationDelay = (i*0.035)+"s"; cell.classList.add("flap--flip"); }
    }
  }

  // ----- render: board -----
  function renderBoard(state) {
    const b = state.brief, it = state.itinerary;
    setField("from", b.origin ? iata(b.origin) : "");
    setField("to", b.destinations && b.destinations.length ? b.destinations[0].city : "");
    setField("days", b.duration_days ? String(b.duration_days).padStart(2,"0") : "");
    setField("date", fmtDateShort(b.travel_date));
    setField("pax", b.traveller_count ? String(b.traveller_count).padStart(2,"0") : "");
    const has = b.origin || (b.destinations||[]).length || b.duration_days || b.travel_date;
    setField("status", it ? "PLANNED" : (has ? "PLANNING" : ""));
    $("#boardSub").textContent = it ? `${it.days.length} days · ${rupee(it.total_cost_inr)}`
      : has ? "building your brief" : "awaiting your trip";
  }

  // ----- render: plan -----
  function rooms(pax){ return Math.max(1, Math.floor((pax+2)/3)); }

  function renderPlan(state) {
    const it = state.itinerary;
    const hero = $("#hero"), plan = $("#plan");
    if (!it) { document.body.dataset.state = "empty"; hero.hidden = false; plan.hidden = true; return; }
    document.body.dataset.state = "planned"; hero.hidden = true; plan.hidden = false;
    const b = it.brief;

    $("#planTotal").textContent = rupee(it.total_cost_inr);
    const note = $("#planTotalNote");
    if (b.budget_mode === "cap" && b.budget_max_inr) {
      const over = it.total_cost_inr > b.budget_max_inr;
      note.textContent = over ? `over your ${rupee(b.budget_max_inr)} cap by ${rupee(it.total_cost_inr-b.budget_max_inr)}` : `within your ${rupee(b.budget_max_inr)} cap`;
      note.classList.toggle("over", over);
    } else { note.textContent = b.budget_mode === "cheapest" ? "cheapest realistic plan" : `${b.traveller_count} travellers · ${rooms(b.traveller_count)} room(s)`; note.classList.remove("over"); }

    const legs = $("#planLegs"); legs.innerHTML = "";
    legs.appendChild(el("span","leg", `<b>${esc(iata(b.origin))}</b> start`));
    (b.destinations||[]).forEach(s => legs.appendChild(el("span","leg", `<b>${esc(s.city)}</b> ${s.nights}n`)));

    // route
    const route = $("#route"); route.innerHTML = "";
    it.days.forEach(d => {
      const day = el("div","day");
      day.appendChild(el("span","day__node"));
      const card = el("div","day__card");
      card.appendChild(el("div","day__head",
        `<span class="day__num">DAY ${String(d.day_number).padStart(2,"0")}</span>`+
        `<span class="day__city">${esc(d.city)}</span>`+
        `<span class="day__date">${esc(fmtDateLong(d.date))}</span>`+
        `<span class="day__cost">${rupee(d.cost_inr)}</span>`));
      const events = el("div","events");
      d.events.slice().sort((a,b)=>a.time.localeCompare(b.time)).forEach(ev => {
        const [icon, mod] = eventKind(ev.kind);
        const row = el("div","event" + (mod ? " event--"+mod : ""));
        row.innerHTML =
          `<span class="event__time">${esc(ev.time)}</span>`+
          `<span class="event__icon">${ICON[icon]}</span>`+
          `<span class="event__body"><div class="event__title">${esc(ev.title)}</div>`+
            (ev.note ? `<div class="event__note">${esc(ev.note)}</div>` : "") + `</span>`+
          `<span class="event__cost">${ev.cost_inr ? rupee(ev.cost_inr) : ""}</span>`;
        events.appendChild(row);
      });
      card.appendChild(events); day.appendChild(card); route.appendChild(day);
    });

    // bookings
    const book = $("#bookings"); book.innerHTML = "";
    const pax = b.traveller_count;
    if (it.flight) {
      const f = it.flight, t = el("div","ticket");
      t.innerHTML =
        `<div class="ticket__kind"><span>Boarding pass</span><span class="code">${esc(f.flight_id)}</span></div>`+
        `<div class="ticket__body"><div class="ticket__route">`+
          `<span class="ticket__iata">${esc(f.origin)}</span><span class="ticket__path"></span><span class="ticket__iata">${esc(f.destination)}</span></div>`+
          `<div class="ticket__name">${esc(f.airline)}</div>`+
          `<div class="ticket__meta">${esc(f.depart_time.split("T")[1]?.slice(0,5)||"")} → ${esc(f.arrive_time.split("T")[1]?.slice(0,5)||"")} · ${f.stops} stop(s)</div></div>`+
        `<div class="ticket__stub">`+
          `<div class="stub"><span class="stub__label">Per ticket</span><span class="stub__value">${rupee(f.price_inr)}</span></div>`+
          `<div class="stub stub--accent"><span class="stub__label">× ${pax} pax</span><span class="stub__value">${rupee(f.price_inr*pax)}</span></div>`+
          `<div class="stub"><span class="stub__label">Date</span><span class="stub__value">${esc(fmtDateShort(b.travel_date))}</span></div></div>`;
      book.appendChild(t);
    } else {
      const t = el("div","ticket");
      t.innerHTML = `<div class="ticket__kind"><span>Ground transit</span><span class="code">DAY 1</span></div>`+
        `<div class="ticket__body"><div class="ticket__name">No flight on this trip</div>`+
        `<div class="ticket__meta">${esc(iata(b.origin))} → ${esc((b.destinations[0]||{}).city||"")} overland. See Day 1 for the route.</div></div>`;
      book.appendChild(t);
    }
    (it.hotels||[]).forEach((h,i) => {
      const stop = b.destinations[i]; const nights = stop ? stop.nights : 1; const rm = rooms(pax);
      const t = el("div","ticket");
      t.innerHTML =
        `<div class="ticket__kind"><span>Reservation</span><span class="code">${esc(h.hotel_id)}</span></div>`+
        `<div class="ticket__body"><div class="ticket__name">${esc(h.name)}</div>`+
          `<div class="ticket__meta">${esc(h.city)} · <span class="star">★ ${h.rating}</span> · ${nights} night(s) · ${rm} room(s)</div></div>`+
        `<div class="ticket__stub">`+
          `<div class="stub"><span class="stub__label">Per night/room</span><span class="stub__value">${rupee(h.price_per_night_inr)}</span></div>`+
          `<div class="stub stub--accent"><span class="stub__label">Stay total</span><span class="stub__value">${rupee(h.price_per_night_inr*nights*rm)}</span></div></div>`;
      book.appendChild(t);
    });

    // kin
    const kinWrap = $("#kinWrap"), kin = $("#kin"); kin.innerHTML = "";
    const sim = it.similar_travelers || [];
    kinWrap.hidden = sim.length === 0;
    sim.forEach(p => {
      const pct = Math.round((p.similarity||0)*100);
      const c = el("div","kincard");
      c.innerHTML =
        `<div class="kincard__match"><span class="kincard__bar"><span style="width:${pct}%"></span></span><span class="kincard__pct">${pct}% match</span></div>`+
        `<div class="kincard__summary">${esc(p.summary)}</div>`+
        `<div class="kincard__chips">${(p.chosen||[]).map(c=>`<span class="chip-sm">${esc(c)}</span>`).join("")}`+
          (p.budget_inr?`<span class="chip-sm">~${rupee(p.budget_inr)}</span>`:"")+`</div>`;
      kin.appendChild(c);
    });
  }

  // ----- render: chat -----
  function bubble(role, html) {
    const m = el("div","msg msg--"+(role==="user"?"user":"agent"));
    m.appendChild(el("div","msg__who", role==="user"?"You":"Safar"));
    m.appendChild(el("div","msg__bubble", html));
    return m;
  }
  function renderThread(state, suggestions) {
    const thread = $("#thread"); thread.innerHTML = "";
    const hist = state.history || [];
    if (!hist.length) {
      thread.appendChild(bubble("agent", md(
        "Hi — I'm **Safar**. Tell me anything about your trip, even just *“I want to plan a trip”*. I'll ask what I still need, suggest places that fit, then build it day by day.\n\n"+
        "**Try:**\n- *5-day adventure trip from Bangalore, budget 50000*\n- *Plan a religious trip from Delhi for 4 days under 25k*\n- *Honeymoon from Mumbai in August*")));
    } else {
      hist.forEach(m => thread.appendChild(bubble(m.role, md(m.content))));
    }
    if (suggestions && suggestions.length) {
      const wrap = el("div","suggest");
      suggestions.forEach(s => {
        const chip = el("button","suggest__chip");
        chip.type = "button";
        chip.innerHTML = `<b>${esc(s.city)}</b> ${s.rough_cost_inr?`<span class="cost">~${rupee(s.rough_cost_inr)}</span>`:""}<br><span class="why">${esc(s.why)}</span>`;
        chip.addEventListener("click", () => send(s.city));
        wrap.appendChild(chip);
      });
      const last = thread.querySelector(".msg--agent:last-of-type");
      (last || thread).appendChild(wrap);
    }
    thread.scrollTop = thread.scrollHeight;
  }

  // ----- render: flags + meter -----
  function renderFlags(flags) {
    const f = $("#flags"); f.innerHTML = "";
    if (!flags.llm_live) f.appendChild(el("span","flag flag--warn","demo · add GEMINI key to chat live"));
    else f.appendChild(el("span","flag flag--ok","live planning"));
    f.appendChild(el("span","flag", flags.search_live ? "fares: live" : "fares: sample"));
  }
  function renderMeter(state, flags) {
    $("#meter").textContent = `session ${esc(state.session_id)} · ${state.llm_calls}/${flags.llm_calls_max} planner calls`;
  }

  // ----- apply a full payload -----
  let lastFlags = { llm_live:false, search_live:false, llm_calls_max:80 };
  function apply(payload, suggestions) {
    const state = payload.state; lastFlags = payload.flags || lastFlags;
    renderFlags(lastFlags);
    renderBoard(state);
    renderPlan(state);
    renderThread(state, suggestions);
    renderMeter(state, lastFlags);
  }

  // ----- network -----
  async function api(path, body) {
    const opt = body ? { method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({ sid, ...body }) } : {};
    const r = await fetch(path + (body?"":`?sid=${encodeURIComponent(sid)}`), opt);
    if (!r.ok) throw new Error((await r.json().catch(()=>({}))).error || r.statusText);
    return r.json();
  }

  let busy = false;
  function setBusy(v){ busy = v; $("#send").disabled = v; $("#input").disabled = v; }

  async function send(message) {
    message = (message||"").trim(); if (!message || busy) return;
    setBusy(true);
    const thread = $("#thread");
    // optimistic echo + typing
    thread.querySelectorAll(".suggest").forEach(n=>n.remove());
    thread.appendChild(bubble("user", esc(message)));
    const typing = bubble("agent", '<span class="typing"><i></i><i></i><i></i></span>');
    thread.appendChild(typing); thread.scrollTop = thread.scrollHeight;
    $("#input").value = "";
    try {
      const payload = await api("/api/chat", { message });
      apply(payload, (payload.reply && payload.reply.suggestions) || []);
    } catch (e) {
      typing.querySelector(".msg__bubble").innerHTML = `Something went wrong: ${esc(e.message)}. Try again.`;
    } finally { setBusy(false); $("#input").focus(); }
  }

  // ----- wire up -----
  function init() {
    buildFlaps();
    $("#form").addEventListener("submit", e => { e.preventDefault(); send($("#input").value); });
    $("#sampleBtn").addEventListener("click", async () => {
      setBusy(true);
      try { apply(await api("/api/sample", {}), []); } finally { setBusy(false); }
      $("#canvas").scrollIntoView({ behavior: REDUCED?"auto":"smooth" });
    });
    $("#resetBtn").addEventListener("click", async () => {
      if (!confirm("Start a brand-new trip? This clears the current conversation.")) return;
      apply(await api("/api/reset", {}), []);
    });
    api("/api/state").then(p => apply(p, [])).catch(()=>apply({state:{history:[],brief:{},itinerary:null,llm_calls:0,session_id:sid},flags:lastFlags},[]));
  }
  document.addEventListener("DOMContentLoaded", init);
})();
