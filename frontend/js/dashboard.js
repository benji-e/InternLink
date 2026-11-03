/* =====================================================================
   dashboard.js - page shell: login check, switching between views,
   the Overview view and log out.
   Needs api.js and the view scripts loaded before it. Each view script
   registers  IL.views.<name> = { load: function () {...} }.
   ===================================================================== */
(function () {
  "use strict";

  var HOME_URL = "/index.html";
  var VIEWS = ["overview", "opportunities", "recommendations", "applications", "profile"];
  var loaded = {};

  IL.views = IL.views || {};

  /** Make a view reload the next time it is shown (after an apply, withdraw or profile save). */
  IL.invalidate = function (names) {
    [].concat(names).forEach(function (name) { loaded[name] = false; });
  };

  function viewFromHash() {
    var name = window.location.hash.replace("#", "");
    return VIEWS.indexOf(name) >= 0 ? name : "overview";
  }

  function showView(name) {
    VIEWS.forEach(function (view) {
      document.getElementById("view-" + view).hidden = (view !== name);
    });
    IL.qsa("[data-view]").forEach(function (link) {
      var active = link.getAttribute("data-view") === name;
      link.classList.toggle("active", active);
      if (active) link.setAttribute("aria-current", "page"); else link.removeAttribute("aria-current");
    });
    var view = IL.views[name];
    if (view && view.load && !loaded[name]) {
      loaded[name] = true;
      view.load();
    }
    window.scrollTo(0, 0);
  }

  window.addEventListener("hashchange", function () { showView(viewFromHash()); });

  // ------------------------------------------------------------------
  // Overview
  // ------------------------------------------------------------------
  var overviewError = document.getElementById("overview-error");

  /** Run a request; on failure remember the message and resolve to null so the other parts still show. */
  function attempt(promise, failures) {
    return promise.catch(function (error) { failures.push(error.message); return null; });
  }

  function statCard(label, value, extra) {
    return '<div class="dash-card"><div class="muted">' + IL.esc(label) + '</div>' +
      '<div class="stat-value">' + IL.esc(value) + '</div>' + (extra || "") + "</div>";
  }

  function loadOverview() {
    var failures = [];
    IL.hideAlert(overviewError);

    Promise.all([
      attempt(IL.get("/api/profile"), failures),
      attempt(IL.get("/api/applications"), failures),
      attempt(IL.get("/api/recommendations", { limit: 3 }), failures)
    ]).then(function (results) {
      var profile = results[0] && results[0].profile;
      var applications = (results[1] && results[1].applications) || [];
      var recommendations = (results[2] && results[2].recommendations) || [];

      if (failures.length) IL.showAlert(overviewError, failures[0]);

      if (profile) {
        var first = (profile.full_name || "").split(" ")[0];
        document.getElementById("welcome-title").textContent = first ? "Welcome, " + first : "Welcome";
      }

      var active = applications.filter(function (a) { return a.status !== "withdrawn" && a.status !== "rejected"; }).length;
      var completeness = profile ? Math.round(profile.completeness || 0) : 0;
      var stats = "";
      if (profile) {
        stats += statCard("Profile completeness", completeness + "%",
          '<div class="progress" aria-hidden="true"><span style="width:' + completeness + '%"></span></div>' +
          (completeness < 100 ? '<p class="mb-0 mt-1"><a href="#profile">Complete your profile</a></p>' : ""));
        stats += statCard("Profile status", profile.verified ? "Verified" : "Awaiting verification",
          profile.verified ? "" : '<p class="muted mb-0 mt-1">Your university coordinator verifies your profile.</p>');
      }
      stats += statCard("Applications sent", applications.length);
      stats += statCard("Still in progress", active);
      document.getElementById("overview-stats").innerHTML = stats;

      var matches = document.getElementById("overview-matches");
      matches.innerHTML = recommendations.length
        ? recommendations.map(function (r) { return IL.renderOpportunityCard(r); }).join("")
        : '<div class="dash-card empty muted">No matches yet. Add skills to your profile to see recommendations.</div>';

      var list = document.getElementById("overview-applications");
      list.innerHTML = applications.length
        ? '<div class="dash-card table-wrap"><table><tbody>' +
          applications.slice(0, 5).map(function (a) {
            return "<tr><td><strong>" + IL.esc(a.title) + "</strong><br><span class=\"muted\">" + IL.esc(a.company_name) +
              "</span></td><td>" + IL.statusBadge(a.status, a.status_label) + "</td></tr>";
          }).join("") + "</tbody></table></div>"
        : '<div class="dash-card empty muted">You have not applied yet. <a href="#opportunities">Browse opportunities</a>.</div>';
    });
  }

  IL.views.overview = { load: loadOverview };

  // ------------------------------------------------------------------
  // Header and log out
  // ------------------------------------------------------------------
  document.getElementById("logout-button").addEventListener("click", function (event) {
    var button = event.currentTarget;
    IL.setBusy(button, true, "Logging out...");
    IL.post("/api/auth/logout", {}, { noRedirect: true })
      .catch(function () { /* leave anyway; the session may already be gone */ })
      .then(function () { window.location.href = HOME_URL; });
  });

  // ------------------------------------------------------------------
  // Start: a 401 here sends the student back to the home page automatically.
  // ------------------------------------------------------------------
  IL.get("/api/auth/me")
    .then(function (data) {
      var name = data.user && data.user.full_name;
      if (name) document.getElementById("header-name").textContent = name;
      showView(viewFromHash());
    })
    .catch(function (error) {
      if (error.status !== 401) {
        IL.toast(error.message, "error");
        showView(viewFromHash());
      }
    });
})();