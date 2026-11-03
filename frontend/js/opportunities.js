/* =====================================================================
   opportunities.js - search and browse open internships, show details.
   Exposes IL.renderOpportunityCard(item, extraHtml) and
   IL.showOpportunity(id), also used by the Overview and Recommended views.

   Assumed endpoints (change here if your router.py differs):
     GET /api/opportunities?q=&location=&page=
         -> { opportunities: [ {opportunity_id, title, company_name, location, sector, duration,
                                deadline, days_left, match_score, already_applied} ],
              page, pages, total }
     GET /api/opportunities/<id>
         -> { opportunity: { ...the fields above, description, requirements, skills: [..],
                             allowance, slots } }
   ===================================================================== */
(function () {
  "use strict";

  var searchInput = document.getElementById("opp-search");
  var locationInput = document.getElementById("opp-location");
  var listBox = document.getElementById("opp-list");
  var errorBox = document.getElementById("opp-error");
  var countLabel = document.getElementById("opp-count");
  var pager = document.getElementById("opp-pager");
  var pageLabel = document.getElementById("opp-page");
  var prevButton = document.getElementById("opp-prev");
  var nextButton = document.getElementById("opp-next");

  var page = 1;
  var pages = 1;
  var requestCount = 0;

  // ------------------------------------------------------------------
  // Shared card (used by three views)
  // ------------------------------------------------------------------
  IL.renderOpportunityCard = function (o, extraHtml) {
    var deadline = IL.daysLeft(o.days_left);
    var meta = [];
    if (o.location) meta.push("<span>" + IL.esc(o.location) + "</span>");
    if (o.sector) meta.push("<span>" + IL.esc(o.sector) + "</span>");
    if (o.duration) meta.push("<span>" + IL.esc(o.duration) + "</span>");
    if (o.deadline) meta.push('<span class="' + deadline.cls + '">Closes ' + IL.esc(IL.formatDate(o.deadline)) +
      (deadline.text ? " (" + IL.esc(deadline.text) + ")" : "") + "</span>");

    var score = (o.match_score === null || o.match_score === undefined) ? "" :
      '<span class="badge ' + IL.matchClass(o.match_score) + '" title="How well this fits your profile">' +
      IL.esc(IL.formatScore(o.match_score)) + " match</span>";

    var closed = o.days_left !== null && o.days_left !== undefined && o.days_left < 0;
    var apply = o.already_applied
      ? '<button type="button" class="btn btn-outline" disabled>Applied</button>'
      : closed
        ? '<button type="button" class="btn btn-outline" disabled>Closed</button>'
        : '<button type="button" class="btn btn-primary" data-apply="' + IL.esc(o.opportunity_id) +
          '" data-title="' + IL.esc(o.title) + '">Apply</button>';

    return '<article class="dash-card opp-card">' +
      '<div class="opp-top"><div><h3 class="opp-title">' + IL.esc(o.title) + '</h3>' +
      '<div class="muted">' + IL.esc(o.company_name) + "</div></div>" + score + "</div>" +
      '<div class="opp-meta muted">' + meta.join("") + "</div>" +
      (extraHtml || "") +
      '<div class="opp-actions"><button type="button" class="btn btn-outline" data-opp-view="' +
      IL.esc(o.opportunity_id) + '">View details</button>' + apply + "</div></article>";
  };

  // ------------------------------------------------------------------
  // List, search and paging
  // ------------------------------------------------------------------
  function load() {
    var ticket = ++requestCount;
    IL.hideAlert(errorBox);
    listBox.innerHTML = '<p class="muted">Loading opportunities...</p>';

    IL.get("/api/opportunities", {
      q: searchInput.value.trim(),
      location: locationInput.value.trim(),
      page: page
    })
      .then(function (data) {
        if (ticket !== requestCount) return;          // a newer search already started
        var items = data.opportunities || [];
        pages = data.pages || 1;
        page = data.page || page;

        countLabel.textContent = data.total === undefined ? "" : data.total + (data.total === 1 ? " opportunity" : " opportunities");
        listBox.innerHTML = items.length
          ? items.map(function (o) { return IL.renderOpportunityCard(o); }).join("")
          : '<div class="dash-card empty muted">No opportunities match your search. Try fewer or different words.</div>';

        pager.hidden = pages <= 1;
        pageLabel.textContent = "Page " + page + " of " + pages;
        prevButton.disabled = page <= 1;
        nextButton.disabled = page >= pages;
      })
      .catch(function (error) {
        if (ticket !== requestCount) return;
        listBox.innerHTML = "";
        pager.hidden = true;
        IL.showAlert(errorBox, error.message);
      });
  }

  var searchAgain = IL.debounce(function () { page = 1; load(); }, 350);
  searchInput.addEventListener("input", searchAgain);
  locationInput.addEventListener("input", searchAgain);
  prevButton.addEventListener("click", function () { if (page > 1) { page--; load(); } });
  nextButton.addEventListener("click", function () { if (page < pages) { page++; load(); } });

  IL.views = IL.views || {};
  IL.views.opportunities = { load: load };

  // ------------------------------------------------------------------
  // Details dialog
  // ------------------------------------------------------------------
  var modalTitle = document.getElementById("opp-modal-title");
  var modalError = document.getElementById("opp-modal-error");
  var modalBody = document.getElementById("opp-modal-body");
  var modalActions = document.getElementById("opp-modal-actions");

  function row(label, value) {
    return value ? "<dt>" + IL.esc(label) + "</dt><dd>" + IL.esc(value) + "</dd>" : "";
  }

  function paragraph(heading, text) {
    return text ? "<h3>" + IL.esc(heading) + '</h3><p class="detail-body">' + IL.esc(text) + "</p>" : "";
  }

  IL.showOpportunity = function (id) {
    modalTitle.textContent = "Opportunity";
    modalBody.innerHTML = '<p class="muted">Loading...</p>';
    modalActions.innerHTML = "";
    IL.hideAlert(modalError);
    IL.openModal("opp-modal");

    IL.get("/api/opportunities/" + encodeURIComponent(id))
      .then(function (data) {
        var o = data.opportunity;
        if (!o) throw new IL.ApiError(404, "This opportunity could not be found.");
        modalTitle.textContent = o.title;

        var skills = (o.skills || []).map(function (s) {
          var name = typeof s === "string" ? s : s.name;
          return '<span class="chip">' + IL.esc(name) + "</span>";
        }).join("");

        modalBody.innerHTML =
          '<p class="muted">' + IL.esc(o.company_name) + "</p>" +
          '<dl class="dl">' +
            row("Location", o.location) + row("Sector", o.sector) + row("Duration", o.duration) +
            row("Allowance", o.allowance) + row("Places", o.slots) +
            row("Closes", o.deadline ? IL.formatDate(o.deadline) : "") +
          "</dl>" +
          paragraph("About the internship", o.description) +
          paragraph("Requirements", o.requirements) +
          (skills ? '<h3>Skills wanted</h3><div class="chips">' + skills + "</div>" : "");

        var closed = o.days_left !== null && o.days_left !== undefined && o.days_left < 0;
        modalActions.innerHTML = o.already_applied
          ? '<button type="button" class="btn btn-outline" disabled>Applied</button>'
          : closed
            ? '<button type="button" class="btn btn-outline" disabled>Closed</button>'
            : '<button type="button" class="btn btn-primary" data-apply="' + IL.esc(o.opportunity_id) +
              '" data-title="' + IL.esc(o.title) + '">Apply</button>';
      })
      .catch(function (error) {
        modalBody.innerHTML = "";
        IL.showAlert(modalError, error.message);
      });
  };

  // Any element with data-opp-view="<id>" opens the details.
  document.addEventListener("click", function (event) {
    var opener = event.target.closest("[data-opp-view]");
    if (opener) IL.showOpportunity(opener.getAttribute("data-opp-view"));
  });
})();