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
}

function renderProfiles() {
  const select = $("profileSelect");
  select.innerHTML = "";
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
  const data = await api(`/minimums/${encodeURIComponent(profileId)}`, {
    method: "POST",
    body: JSON.stringify(profilePayload()),
  });
  localStorage.setItem("tempest:lastProfile", profileId);
  await loadProfiles();
  fillProfile(data.profile);
}

function listItems(items) {
  if (!items || !items.length) return "<p>None</p>";
  return `<ul>${items.map((item) => `<li>${item}</li>`).join("")}</ul>`;
}

function renderResult(data) {
  const result = $("result");
  const decision = data.decision;
  const weather = data.weather || {};
  const decisionClass = decision.decision === "no-go" ? "no-go" : decision.decision;

  result.innerHTML = `
    <div class="decision ${decisionClass}">
      <div>
        <p class="eyebrow">Decision</p>
        <h2>${decision.decision.toUpperCase()}</h2>
      </div>
      <div>METAR ${data.sources.metar || "unknown"} · TAF ${data.sources.taf || "n/a"} · Airport ${data.sources.airport || "n/a"}</div>
    </div>
    <div class="reason-grid">
      <div class="reason-box"><h3>Failures</h3>${listItems(decision.fail_reasons)}</div>
      <div class="reason-box"><h3>Cautions</h3>${listItems(decision.caution_reasons)}</div>
      <div class="reason-box"><h3>Unknowns</h3>${listItems(decision.unknowns)}</div>
      <div class="reason-box"><h3>Passes</h3>${listItems(decision.pass_reasons)}</div>
    </div>
    <h3 style="margin-top:18px">Best Runway</h3>
    <pre>${JSON.stringify(decision.best_runway || {}, null, 2)}</pre>
    <h3>Raw METAR</h3>
    <pre>${weather.metar?.raw_text || "Unavailable"}</pre>
    <h3>Raw TAF</h3>
    <pre>${weather.taf?.raw_text || data.errors?.taf || "Unavailable"}</pre>
  `;
  result.classList.remove("hidden");
}

async function evaluateFlight() {
  const profileId = $("profileId").value.trim();
  const icao = $("icao").value.trim().toUpperCase();
  if (!profileId || !icao) return;

  localStorage.setItem("tempest:lastIcao", icao);
  localStorage.setItem("tempest:lastProfile", profileId);
  setStatus("Evaluating");

  try {
    const planned = $("plannedDeparture").value;
    const data = await api("/evaluate", {
      method: "POST",
      body: JSON.stringify({
        icao,
        profile_id: profileId,
        planned_departure: planned ? new Date(planned).toISOString() : null,
        taf_lookahead_hours: numberOrNull($("tafLookahead").value) || 3,
        fuel_reserve_min: numberOrNull($("fuelReserve").value),
        include_taf: $("includeTaf").checked,
      }),
    });
    renderResult(data);
    setStatus("Ready");
  } catch (error) {
    $("result").innerHTML = `<div class="decision no-go"><h2>${error.message}</h2></div>`;
    $("result").classList.remove("hidden");
    setStatus("Error");
  }
}

async function init() {
  $("icao").value = localStorage.getItem("tempest:lastIcao") || "KLAF";
  $("plannedDeparture").value = new Date(Date.now() + 60 * 60 * 1000)
    .toISOString()
    .slice(0, 16);
  $("minimumsForm").addEventListener("submit", saveProfile);
  $("profileSelect").addEventListener("change", (event) => {
    const profile = state.profiles.find((item) => item.profile_id === event.target.value);
    if (profile) fillProfile(profile);
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
