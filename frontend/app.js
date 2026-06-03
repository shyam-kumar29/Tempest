const state = {
  profiles: [],
  selectedProfile: null,
};

const fields = [
  "min_ceiling_ft_agl",
  "min_visibility_sm",
  "max_surface_wind_kt",
  "max_crosswind_kt",
  "max_gust_kt",
  "max_tailwind_kt",
  "min_runway_length_ft",
  "min_runway_width_ft",
  "min_fuel_reserve_day_min",
  "min_fuel_reserve_night_min",
  "max_density_altitude_ft",
];

function $(id) {
  return document.getElementById(id);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function numberOrNull(value) {
  if (value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function checkedOrNull(form, name) {
  const field = form.elements[name];
  return field.checked ? true : null;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || `Request failed: ${response.status}`);
  }
  return data;
}

function setStatus(text) {
  $("apiStatus").textContent = text;
}

function openSettings() {
  $("settingsOverlay").classList.remove("hidden");
}

function closeSettings() {
  $("settingsOverlay").classList.add("hidden");
}

function profilePayload() {
  const form = $("minimumsForm");
  const payload = {
    display_name: $("displayName").value.trim(),
    allow_ifr: checkedOrNull(form, "allow_ifr"),
    allow_night: checkedOrNull(form, "allow_night"),
    require_dry_runway: checkedOrNull(form, "require_dry_runway"),
  };

  for (const field of fields) {
    payload[field] = numberOrNull(form.elements[field].value);
  }

  const surfaces = form.elements.allowed_runway_surfaces.value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
  payload.allowed_runway_surfaces = surfaces.length ? surfaces : null;
  return payload;
}

function fillProfile(profile) {
  state.selectedProfile = profile;
  $("profileId").value = profile.profile_id || "";
  $("displayName").value = profile.display_name || "";

  const form = $("minimumsForm");
  for (const field of fields) {
    form.elements[field].value = profile[field] ?? "";
  }
  form.elements.allowed_runway_surfaces.value = (profile.allowed_runway_surfaces || []).join(", ");
  form.elements.allow_ifr.checked = profile.allow_ifr === true;
  form.elements.allow_night.checked = profile.allow_night === true;
  form.elements.require_dry_runway.checked = profile.require_dry_runway === true;
  renderProfileSummary(profile);
}

function profileLimit(profile, field, suffix) {
  const value = profile[field];
  return value === null || value === undefined ? "not set" : `${value}${suffix}`;
}

function renderProfileSummary(profile) {
  const summary = $("profileSummary");
  if (!profile) {
    summary.innerHTML = `
      <p class="empty-state">No saved minimums profile yet.</p>
      <p>Create one once, then keep this section folded unless your limits change.</p>
    `;
    return;
  }

  const surfaces = profile.allowed_runway_surfaces?.length
    ? profile.allowed_runway_surfaces.join(", ")
    : "any";

  summary.innerHTML = `
    <div class="summary-title">
      <strong>${escapeHtml(profile.display_name || profile.profile_id)}</strong>
      <span>${escapeHtml(profile.profile_id)}</span>
    </div>
    <dl class="limit-list">
      <div><dt>Ceiling</dt><dd>${escapeHtml(profileLimit(profile, "min_ceiling_ft_agl", " ft"))}</dd></div>
      <div><dt>Visibility</dt><dd>${escapeHtml(profileLimit(profile, "min_visibility_sm", " SM"))}</dd></div>
      <div><dt>Crosswind</dt><dd>${escapeHtml(profileLimit(profile, "max_crosswind_kt", " kt"))}</dd></div>
      <div><dt>Wind / Gust</dt><dd>${escapeHtml(profileLimit(profile, "max_surface_wind_kt", " kt"))} / ${escapeHtml(profileLimit(profile, "max_gust_kt", " kt"))}</dd></div>
      <div><dt>Runway</dt><dd>${escapeHtml(profileLimit(profile, "min_runway_length_ft", " ft"))} x ${escapeHtml(profileLimit(profile, "min_runway_width_ft", " ft"))}</dd></div>
      <div><dt>Surfaces</dt><dd>${escapeHtml(surfaces)}</dd></div>
    </dl>
  `;
}

function renderProfiles() {
  const select = $("profileSelect");
  select.innerHTML = "";

  if (!state.profiles.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "Create a profile first";
    select.appendChild(option);
    state.selectedProfile = null;
    renderProfileSummary(null);
    openSettings();
    return;
  }

  for (const profile of state.profiles) {
    const option = document.createElement("option");
    option.value = profile.profile_id;
    option.textContent = profile.display_name || profile.profile_id;
    select.appendChild(option);
  }

  const lastProfile = localStorage.getItem("tempest:lastProfile");
  const selected = state.profiles.find((item) => item.profile_id === lastProfile) || state.profiles[0];
  if (selected) {
    select.value = selected.profile_id;
    fillProfile(selected);
    closeSettings();
  }
}

async function loadProfiles() {
  const data = await api("/minimums");
  state.profiles = data.profiles || [];
  renderProfiles();
}

async function saveProfile(event) {
  event.preventDefault();
  const profileId = $("profileId").value.trim();
  if (!profileId) return;

  setStatus("Saving minimums");
  try {
    const data = await api(`/minimums/${encodeURIComponent(profileId)}`, {
      method: "POST",
      body: JSON.stringify(profilePayload()),
    });
    localStorage.setItem("tempest:lastProfile", profileId);
    await loadProfiles();
    fillProfile(data.profile);
    $("profileSelect").value = profileId;
    closeSettings();
    setStatus("Ready");
  } catch (error) {
    setStatus("Minimums save failed");
    $("result").innerHTML = `<div class="decision no-go"><h2>${escapeHtml(error.message)}</h2></div>`;
    $("result").classList.remove("hidden");
  }
}

function listItems(items) {
  if (!items || !items.length) return "<p>None</p>";
  return `<ul>${items.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`;
}

function bestRunwaySummary(bestRunway) {
  if (!bestRunway) return "<p>No runway recommendation available.</p>";
  return `<pre>${escapeHtml(JSON.stringify(bestRunway, null, 2))}</pre>`;
}

function rawText(value, fallback) {
  return `<pre>${escapeHtml(value || fallback)}</pre>`;
}

function localDateTimeValue(date) {
  const offsetMs = date.getTimezoneOffset() * 60 * 1000;
  return new Date(date.getTime() - offsetMs).toISOString().slice(0, 16);
}

function renderResult(data) {
  const result = $("result");
  const decision = data.decision;
  const weather = data.weather || {};
  const sources = data.sources || {};
  const errors = data.errors || {};
  const decisionClass = decision.decision === "no-go" ? "no-go" : decision.decision;

  result.innerHTML = `
    <div class="decision ${escapeHtml(decisionClass)}">
      <div>
        <p class="eyebrow">Decision</p>
        <h2>${escapeHtml(decision.decision.toUpperCase())}</h2>
      </div>
      <div class="source-row">
        METAR ${escapeHtml(sources.metar || "unknown")}
        <span>TAF ${escapeHtml(sources.taf || "n/a")}</span>
        <span>Airport ${escapeHtml(sources.airport || "n/a")}</span>
      </div>
    </div>
    <div class="reason-grid">
      <div class="reason-box failure"><h3>Failures</h3>${listItems(decision.fail_reasons)}</div>
      <div class="reason-box caution-box"><h3>Cautions</h3>${listItems(decision.caution_reasons)}</div>
      <div class="reason-box unknown"><h3>Unknowns</h3>${listItems(decision.unknowns)}</div>
      <div class="reason-box pass"><h3>Passes</h3>${listItems(decision.pass_reasons)}</div>
    </div>
    <div class="details-grid">
      <section>
        <h3>Best Runway</h3>
        ${bestRunwaySummary(decision.best_runway)}
      </section>
      <section>
        <h3>Airport / TAF Notes</h3>
        ${listItems([errors.airport, errors.taf].filter(Boolean))}
      </section>
    </div>
    <h3 class="data-heading">Raw METAR</h3>
    ${rawText(weather.metar?.raw_text, "Unavailable")}
    <h3 class="data-heading">Raw TAF</h3>
    ${rawText(weather.taf?.raw_text, errors.taf || "Unavailable")}
  `;
  result.classList.remove("hidden");
  result.scrollIntoView({ behavior: "smooth", block: "start" });
}

function plannedDepartureIso() {
  const planned = $("plannedDeparture").value;
  if (!planned) return null;
  const date = new Date(planned);
  if (Number.isNaN(date.getTime())) {
    throw new Error("Planned departure is not a valid date/time");
  }
  return date.toISOString();
}

async function evaluateFlight() {
  const selectedProfileId = $("profileSelect").value || $("profileId").value.trim();
  const icao = $("icao").value.trim().toUpperCase();

  if (!selectedProfileId) {
    openSettings();
    setStatus("Create minimums first");
    $("result").innerHTML = `<div class="decision caution"><h2>Create a minimums profile before evaluating.</h2></div>`;
    $("result").classList.remove("hidden");
    return;
  }
  if (!icao) {
    setStatus("Airport required");
    $("icao").focus();
    return;
  }

  localStorage.setItem("tempest:lastIcao", icao);
  localStorage.setItem("tempest:lastProfile", selectedProfileId);
  setStatus("Evaluating");

  try {
    const data = await api("/evaluate", {
      method: "POST",
      body: JSON.stringify({
        icao,
        profile_id: selectedProfileId,
        planned_departure: plannedDepartureIso(),
        taf_lookahead_hours: numberOrNull($("tafLookahead").value) || 3,
        fuel_reserve_min: numberOrNull($("fuelReserve").value),
        include_taf: $("includeTaf").checked,
      }),
    });
    renderResult(data);
    setStatus("Ready");
  } catch (error) {
    $("result").innerHTML = `<div class="decision no-go"><h2>${escapeHtml(error.message)}</h2></div>`;
    $("result").classList.remove("hidden");
    setStatus("Error");
  }
}

async function init() {
  $("icao").value = localStorage.getItem("tempest:lastIcao") || "KLAF";
  $("plannedDeparture").value = localDateTimeValue(new Date(Date.now() + 60 * 60 * 1000));
  $("minimumsForm").addEventListener("submit", saveProfile);
  $("profileSelect").addEventListener("change", (event) => {
    const profile = state.profiles.find((item) => item.profile_id === event.target.value);
    if (profile) {
      localStorage.setItem("tempest:lastProfile", profile.profile_id);
      fillProfile(profile);
    }
  });
  $("settingsButton").addEventListener("click", openSettings);
  $("closeSettingsButton").addEventListener("click", closeSettings);
  $("settingsOverlay").addEventListener("click", (event) => {
    if (event.target === $("settingsOverlay")) closeSettings();
  });
  $("evaluateButton").addEventListener("click", evaluateFlight);

  try {
    await api("/health");
    setStatus("Ready");
    await loadProfiles();
    if (!state.profiles.length) {
      $("profileId").value = "primary";
      $("displayName").value = "Primary Profile";
    }
  } catch (error) {
    setStatus(error.message);
  }
}

init();
