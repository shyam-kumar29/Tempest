const state = {
  profiles: [],
  selectedProfile: null,
  busy: false,
  aiStatus: null,
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
  "recommendation_radius_nm",
  "recommendation_count",
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

function setBusy(isBusy) {
  state.busy = isBusy;
  for (const id of ["evaluateButton", "recommendButton", "settingsButton", "closeSettingsButton"]) {
    const element = $(id);
    if (element) element.disabled = isBusy;
  }
  const saveButton = document.querySelector("#minimumsForm button[type='submit']");
  if (saveButton) saveButton.disabled = isBusy;
}

async function api(path, options = {}) {
  const timeoutMs = options.timeoutMs || 60000;
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(path, {
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      ...options,
      signal: controller.signal,
    }).catch((error) => {
      if (error.name === "AbortError") {
        throw new Error("Request timed out. Try a smaller recommendation count or radius.");
      }
      throw error;
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data.detail || `Request failed: ${response.status}`);
    }
    return data;
  } finally {
    window.clearTimeout(timeoutId);
  }
}

function setStatus(text) {
  $("apiStatus").textContent = text;
}

function openSettings() {
  $("settingsOverlay").classList.remove("hidden");
  $("settingsOverlay").dataset.open = "true";
}

function closeSettings() {
  $("settingsOverlay").classList.add("hidden");
  delete $("settingsOverlay").dataset.open;
}

function profilePayload() {
  const form = $("minimumsForm");
  const payload = {
    display_name: $("displayName").value.trim(),
    home_airport: $("homeAirport").value.trim().toUpperCase() || null,
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
  $("homeAirport").value = profile.home_airport || "";

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
      <div><dt>Home</dt><dd>${escapeHtml(profile.home_airport || "not set")}</dd></div>
      <div><dt>Recommendations</dt><dd>${escapeHtml(profileLimit(profile, "recommendation_radius_nm", " NM"))} / ${escapeHtml(profileLimit(profile, "recommendation_count", ""))}</dd></div>
    </dl>
  `;
}

function renderAiStatus() {
  const target = $("aiStatus");
  if (!target) return;
  const status = state.aiStatus;
  if (!status) {
    target.textContent = "Checking AI configuration.";
    return;
  }
  if (status.configured) {
    target.textContent = `AI review is enabled on the server (${status.model}).`;
    return;
  }
  target.textContent = "AI review needs OPENAI_API_KEY set in the server environment. Recommendations still work without AI.";
}

function renderProfiles(selectedProfileId = null) {
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

  const lastProfile = selectedProfileId || localStorage.getItem("tempest:lastProfile");
  const selected = state.profiles.find((item) => item.profile_id === lastProfile) || state.profiles[0];
  if (selected) {
    select.value = selected.profile_id;
    fillProfile(selected);
    closeSettings();
  }
}

function upsertProfileInState(profile) {
  const index = state.profiles.findIndex((item) => item.profile_id === profile.profile_id);
  if (index >= 0) {
    state.profiles[index] = profile;
  } else {
    state.profiles.push(profile);
    state.profiles.sort((a, b) => a.profile_id.localeCompare(b.profile_id));
  }
  state.selectedProfile = profile;
  localStorage.setItem("tempest:lastProfile", profile.profile_id);
  renderProfiles(profile.profile_id);
  fillProfile(profile);
  $("profileSelect").value = profile.profile_id;
}

async function loadProfiles() {
  const data = await api("/minimums");
  state.profiles = data.profiles || [];
  renderProfiles();
}

async function loadAiStatus() {
  try {
    state.aiStatus = await api("/ai/status");
  } catch (error) {
    state.aiStatus = { configured: false, model: null };
  }
  renderAiStatus();
}

async function saveProfile(event) {
  event.preventDefault();
  if (state.busy) return;
  const profileId = $("profileId").value.trim();
  if (!profileId) return;

  setStatus("Saving minimums");
  setBusy(true);
  try {
    const data = await api(`/minimums/${encodeURIComponent(profileId)}`, {
      method: "POST",
      body: JSON.stringify(profilePayload()),
    });
    upsertProfileInState(data.profile);
    closeSettings();
    setStatus("Ready");
  } catch (error) {
    setStatus("Minimums save failed");
    $("result").innerHTML = `<div class="decision no-go"><h2>${escapeHtml(error.message)}</h2></div>`;
    $("result").classList.remove("hidden");
  } finally {
    setBusy(false);
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

function decisionClassFor(decision) {
  return decision === "no-go" ? "no-go" : decision;
}

function formatValue(value, suffix = "") {
  return value === null || value === undefined || value === "" ? "Unavailable" : `${value}${suffix}`;
}

function formatWind(direction, speed, gust) {
  if (speed === null || speed === undefined) return "Unavailable";
  const directionText =
    direction === null || direction === undefined || direction === "" ? "Direction unavailable" : `${direction}`;
  const gustText = gust === null || gust === undefined ? "" : `G${gust}`;
  return `${directionText} at ${speed}${gustText} kt`;
}

function decodedRows(rows) {
  return `
    <dl class="decoded-list">
      ${rows
        .map(
          ([label, value]) => `
            <div>
              <dt>${escapeHtml(label)}</dt>
              <dd>${escapeHtml(value)}</dd>
            </div>
          `
        )
        .join("")}
    </dl>
  `;
}

function metarCoversPlannedDeparture(summary) {
  if (!summary?.observed_at || !summary?.planned_departure) return false;
  const observed = new Date(summary.observed_at);
  const planned = new Date(summary.planned_departure);
  if (Number.isNaN(observed.getTime()) || Number.isNaN(planned.getTime())) return false;
  const deltaMs = planned.getTime() - observed.getTime();
  return deltaMs >= 0 && deltaMs <= 60 * 60 * 1000;
}

function localDisplayTime(value) {
  if (!value) return "Unavailable";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function renderDecodedWeather(decision) {
  const metar = decision.metar_summary || {};
  const tafPeriods = decision.taf_summary?.evaluated_periods || [];
  const useMetar = metarCoversPlannedDeparture(metar) || !tafPeriods.length;

  if (useMetar) {
    return `
      <aside class="decoded-weather">
        <p class="eyebrow">Decoded METAR</p>
        <h3>Planned Time</h3>
        ${decodedRows([
          ["Observed", metar.observed_at_local || metar.observed_at || "Unavailable"],
          ["Flight category", formatValue(metar.flight_category)],
          ["Visibility", formatValue(metar.visibility_sm, " SM")],
          ["Ceiling", metar.ceiling_ft_agl === null || metar.ceiling_ft_agl === undefined ? "No ceiling parsed" : `${metar.ceiling_ft_agl} ft AGL`],
          ["Wind", formatWind(metar.wind_direction_degrees, metar.wind_speed_kt, metar.wind_gust_kt)],
          ["Density altitude", formatValue(metar.density_altitude_ft, " ft")],
        ])}
      </aside>
    `;
  }

  const period = tafPeriods[0];
  const ceiling =
    period.ceiling_ft_agl === null || period.ceiling_ft_agl === undefined
      ? period.no_ceiling_reported
        ? "No ceiling forecast"
        : "Unavailable"
      : `${period.ceiling_ft_agl} ft AGL`;

  return `
    <aside class="decoded-weather">
      <p class="eyebrow">Decoded TAF</p>
      <h3>Matching Period</h3>
      ${decodedRows([
        ["From", localDisplayTime(period.from)],
        ["To", localDisplayTime(period.to)],
        ["Visibility", period.visibility_display || formatValue(period.visibility_sm, " SM")],
        ["Ceiling", ceiling],
        ["Wind", formatWind(period.wind_direction, period.wind_speed_kt, period.wind_gust_kt)],
      ])}
    </aside>
  `;
}

function localDateTimeValue(date) {
  const offsetMs = date.getTimezoneOffset() * 60 * 1000;
  return new Date(date.getTime() - offsetMs).toISOString().slice(0, 16);
}

function routeTokens(route) {
  return route
    .split(/[\s,;\->]+/)
    .map((item) => item.trim().toUpperCase())
    .filter(Boolean);
}

function numberOrDefault(id, fallback) {
  const value = numberOrNull($(id).value);
  return value === null ? fallback : value;
}

function renderResult(data) {
  const result = $("result");
  const decision = data.decision;
  const weather = data.weather || {};
  const sources = data.sources || {};
  const errors = data.errors || {};
  const decisionClass = decisionClassFor(decision.decision);

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
    <div class="result-body">
      <div class="reason-grid">
        <div class="reason-box failure"><h3>Failures</h3>${listItems(decision.fail_reasons)}</div>
        <div class="reason-box caution-box"><h3>Cautions</h3>${listItems(decision.caution_reasons)}</div>
        <div class="reason-box unknown"><h3>Unknowns</h3>${listItems(decision.unknowns)}</div>
        <div class="reason-box pass"><h3>Passes</h3>${listItems(decision.pass_reasons)}</div>
      </div>
      ${renderDecodedWeather(decision)}
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

function renderRouteLegs(legs) {
  if (!legs || !legs.length) return "<p>No route legs available.</p>";
  return `
    <dl class="route-leg-list">
      ${legs
        .map(
          (leg) => `
            <div>
              <dt>${escapeHtml(leg.from)} to ${escapeHtml(leg.to)}</dt>
              <dd>${escapeHtml(leg.distance_nm)} NM · ${escapeHtml(localDisplayTime(leg.estimated_departure))} to ${escapeHtml(localDisplayTime(leg.estimated_arrival))}</dd>
            </div>
          `
        )
        .join("")}
    </dl>
  `;
}

function renderRouteStation(station) {
  const decision = station.decision || {};
  const decisionClass = decisionClassFor(decision.decision || "caution");
  const title = `${station.role || "station"} · ${station.icao_id}`;
  const errors = station.errors || {};

  return `
    <section class="station-card">
      <div class="station-head">
        <div>
          <p class="eyebrow">${escapeHtml(station.role || "station")}</p>
          <h3>${escapeHtml(station.icao_id)}</h3>
        </div>
        <span class="decision-pill ${escapeHtml(decisionClass)}">${escapeHtml((decision.decision || "unknown").toUpperCase())}</span>
      </div>
      <div class="station-meta">
        <span>${escapeHtml(localDisplayTime(station.planned_time))}</span>
        <span>${escapeHtml(formatValue(station.distance_from_departure_nm, " NM"))}</span>
      </div>
      <div class="result-body station-result-body" aria-label="${escapeHtml(title)} weather details">
        <div class="reason-grid station-reason-grid">
          <div class="reason-box failure"><h3>Failures</h3>${listItems(decision.fail_reasons)}</div>
          <div class="reason-box caution-box"><h3>Cautions</h3>${listItems(decision.caution_reasons)}</div>
          <div class="reason-box unknown"><h3>Unknowns</h3>${listItems(decision.unknowns)}</div>
          <div class="reason-box pass"><h3>Passes</h3>${listItems(decision.pass_reasons)}</div>
        </div>
        ${renderDecodedWeather(decision)}
      </div>
      ${errors.weather ? `<div class="station-error">${escapeHtml(errors.weather)}</div>` : ""}
    </section>
  `;
}

function renderRouteResult(data) {
  const result = $("result");
  const decisionClass = decisionClassFor(data.summary_decision);
  const routeNotes = [...(data.coverage_notes || []), ...(data.index_notes || [])];
  result.innerHTML = `
    <div class="decision ${escapeHtml(decisionClass)}">
      <div>
        <p class="eyebrow">Route Decision</p>
        <h2>${escapeHtml(String(data.summary_decision || "unknown").toUpperCase())}</h2>
      </div>
      <div class="source-row">
        ${escapeHtml((data.route || []).join(" - "))}
        <span>${escapeHtml(data.parameters?.corridor_radius_nm ?? 10)} NM radius</span>
        <span>${escapeHtml(data.parameters?.sample_spacing_nm ?? 25)} NM samples</span>
      </div>
    </div>
    <div class="details-grid route-summary-grid">
      <section>
        <h3>Route Legs</h3>
        ${renderRouteLegs(data.legs)}
      </section>
      <section>
        <h3>Route Notes</h3>
        ${listItems(routeNotes)}
      </section>
    </div>
    <div class="station-list">
      ${(data.stations || []).map(renderRouteStation).join("")}
    </div>
  `;
  result.classList.remove("hidden");
  result.scrollIntoView({ behavior: "smooth", block: "start" });
}

function renderAiBriefing(ai) {
  if (!ai) return "";
  const status = ai.status || "unavailable";
  return `
    <section class="ai-briefing">
      <div class="station-head">
        <div>
          <p class="eyebrow">AI Review</p>
          <h3>${escapeHtml(status === "completed" ? "Advisory Briefing" : "Unavailable")}</h3>
        </div>
        <span class="decision-pill caution">${escapeHtml(status.toUpperCase())}</span>
      </div>
      ${ai.summary ? `<p class="briefing-summary">${escapeHtml(ai.summary)}</p>` : ""}
      ${ai.recommended_action ? `<p class="briefing-action">${escapeHtml(ai.recommended_action)}</p>` : ""}
      <div class="details-grid ai-grid">
        <section><h3>Top Risks</h3>${listItems(ai.top_risks)}</section>
        <section><h3>Best Options</h3>${listItems(ai.best_options)}</section>
        <section><h3>Watch Items</h3>${listItems(ai.watch_items)}</section>
        <section><h3>Questions</h3>${listItems(ai.pilot_questions)}</section>
      </div>
      <div class="station-error">${listItems(ai.limitations)}</div>
    </section>
  `;
}

function renderRecommendationStation(station) {
  const decision = station.decision || {};
  const decisionClass = decisionClassFor(decision.decision || "caution");
  const errors = station.errors || {};
  const name = station.name ? ` · ${station.name}` : "";

  return `
    <section class="station-card recommendation-card">
      <div class="station-head">
        <div>
          <p class="eyebrow">Destination</p>
          <h3>${escapeHtml(station.icao_id)}${escapeHtml(name)}</h3>
        </div>
        <span class="decision-pill ${escapeHtml(decisionClass)}">${escapeHtml((decision.decision || "unknown").toUpperCase())}</span>
      </div>
      <div class="station-meta">
        <span>${escapeHtml(formatValue(station.distance_from_home_nm, " NM"))}</span>
        <span>${escapeHtml(localDisplayTime(station.estimated_arrival || station.planned_time))}</span>
        <span>${escapeHtml(station.airport_type || "weather station")}</span>
      </div>
      <div class="result-body station-result-body">
        <div class="reason-grid station-reason-grid">
          <div class="reason-box failure"><h3>Failures</h3>${listItems(decision.fail_reasons)}</div>
          <div class="reason-box caution-box"><h3>Cautions</h3>${listItems(decision.caution_reasons)}</div>
          <div class="reason-box unknown"><h3>Unknowns</h3>${listItems(decision.unknowns)}</div>
          <div class="reason-box pass"><h3>Passes</h3>${listItems(decision.pass_reasons)}</div>
        </div>
        ${renderDecodedWeather(decision)}
      </div>
      ${errors.weather ? `<div class="station-error">${escapeHtml(errors.weather)}</div>` : ""}
    </section>
  `;
}

function renderHomeSummary(station) {
  const decision = station?.decision || {};
  return decodedRows([
    ["Station", station?.icao_id || "Unavailable"],
    ["Decision", String(decision.decision || "unknown").toUpperCase()],
    ["Planned", localDisplayTime(station?.planned_time)],
    ["Failures", String((decision.fail_reasons || []).length)],
    ["Cautions", String((decision.caution_reasons || []).length)],
    ["Unknowns", String((decision.unknowns || []).length)],
  ]);
}

function renderRecommendationsResult(data) {
  const result = $("result");
  const decisionClass = decisionClassFor(data.summary_decision);
  const notes = [...(data.notes || []), ...(data.index_notes || [])];
  result.innerHTML = `
    <div class="decision ${escapeHtml(decisionClass)}">
      <div>
        <p class="eyebrow">Today</p>
        <h2>${escapeHtml(String(data.summary_decision || "unknown").toUpperCase())}</h2>
      </div>
      <div class="source-row">
        Home ${escapeHtml(data.home_airport || "unknown")}
        <span>${escapeHtml(data.parameters?.radius_nm ?? 150)} NM</span>
        <span>${escapeHtml((data.recommendations || []).length)} options</span>
      </div>
    </div>
    ${renderAiBriefing(data.ai)}
    <div class="details-grid route-summary-grid">
      <section>
        <h3>Home Airport</h3>
        ${renderHomeSummary(data.home)}
      </section>
      <section>
        <h3>Notes</h3>
        ${listItems(notes)}
      </section>
    </div>
    <div class="station-list">
      ${(data.recommendations || []).map(renderRecommendationStation).join("")}
    </div>
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

function selectedProfileId() {
  return $("profileSelect").value || $("profileId").value.trim();
}

async function evaluateFlight() {
  if (state.busy) return;
  const profileId = selectedProfileId();
  const route = $("route").value.trim().toUpperCase();

  if (!profileId) {
    openSettings();
    setStatus("Create minimums first");
    $("result").innerHTML = `<div class="decision caution"><h2>Create a minimums profile before evaluating.</h2></div>`;
    $("result").classList.remove("hidden");
    return;
  }
  if (!route) {
    setStatus("Route required");
    $("route").focus();
    return;
  }

  localStorage.setItem("tempest:lastRoute", route);
  localStorage.setItem("tempest:lastProfile", profileId);
  setStatus("Evaluating");
  setBusy(true);

  try {
    const tokens = routeTokens(route);
    if (tokens.length === 1) {
      const data = await api("/evaluate", {
        method: "POST",
        body: JSON.stringify({
          icao: tokens[0],
          profile_id: profileId,
          planned_departure: plannedDepartureIso(),
          include_taf: true,
        }),
      });
      renderResult(data);
    } else {
      const data = await api("/evaluate-route", {
        method: "POST",
        body: JSON.stringify({
          route,
          profile_id: profileId,
          planned_departure: plannedDepartureIso(),
          include_taf: true,
          corridor_radius_nm: numberOrDefault("corridorRadius", 10),
          sample_spacing_nm: numberOrDefault("sampleSpacing", 25),
          groundspeed_kt: numberOrDefault("groundSpeed", 100),
        }),
      });
      renderRouteResult(data);
    }
    setStatus("Ready");
  } catch (error) {
    $("result").innerHTML = `<div class="decision no-go"><h2>${escapeHtml(error.message)}</h2></div>`;
    $("result").classList.remove("hidden");
    setStatus("Error");
  } finally {
    setBusy(false);
  }
}

async function recommendDestinations() {
  if (state.busy) return;
  const profileId = selectedProfileId();
  if (!profileId) {
    openSettings();
    setStatus("Create minimums first");
    $("result").innerHTML = `<div class="decision caution"><h2>Create a minimums profile before requesting recommendations.</h2></div>`;
    $("result").classList.remove("hidden");
    return;
  }

  const profile = state.profiles.find((item) => item.profile_id === profileId) || state.selectedProfile;
  if (!profile?.home_airport) {
    openSettings();
    setStatus("Home airport required");
    $("result").innerHTML = `<div class="decision caution"><h2>Save a home airport before requesting recommendations.</h2></div>`;
    $("result").classList.remove("hidden");
    return;
  }

  localStorage.setItem("tempest:lastProfile", profileId);
  setStatus("Finding destinations");
  setBusy(true);
  try {
    const data = await api("/recommendations", {
      method: "POST",
      body: JSON.stringify({
        profile_id: profileId,
        planned_departure: plannedDepartureIso(),
        include_ai: $("includeAi").checked,
        groundspeed_kt: numberOrDefault("groundSpeed", 100),
      }),
      timeoutMs: 90000,
    });
    renderRecommendationsResult(data);
    setStatus("Ready");
  } catch (error) {
    $("result").innerHTML = `<div class="decision no-go"><h2>${escapeHtml(error.message)}</h2></div>`;
    $("result").classList.remove("hidden");
    setStatus("Error");
  } finally {
    setBusy(false);
  }
}

async function init() {
  $("route").value = localStorage.getItem("tempest:lastRoute") || "KLAF - KIND";
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
  $("recommendButton").addEventListener("click", recommendDestinations);

  try {
    await api("/health");
    setStatus("Ready");
    await loadAiStatus();
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
