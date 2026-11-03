/* =====================================================================
   applications.js - "My applications" view, the apply dialog and withdraw.
   Exposes IL.openApply(opportunityId, title) for the other views.

   Assumed endpoints (change here if your router.py differs):
     GET  /api/applications                  -> { applications: [ {application_id, opportunity_id, title,
                                                  company_name, status, status_label, applied_at, can_withdraw} ] }
     POST /api/applications                  body { opportunity_id, cover_letter }
     POST /api/applications/<id>/withdraw
   ===================================================================== */
(function () {
  "use strict";

  var listBox = document.getElementById("app-list");
  var listError = document.getElementById("app-error");
  var applyForm = document.getElementById("apply-form");
  var applyError = document.getElementById("apply-error");
  var applySubmit = document.getElementById("apply-submit");
  var applyCover = document.getElementById("apply-cover");
  var applyingTo = null;            // id of the opportunity in the open apply dialog
  var requestCount = 0;

  // ------------------------------------------------------------------
  // List
  // ------------------------------------------------------------------
  function render(applications) {
    if (!applications.length) {
      listBox.innerHTML = '<div class="dash-card empty"><p>You have not applied to anything yet.</p>' +
        '<a class="btn btn-primary" href="#opportunities">Browse opportunities</a></div>';
      return;
    }
    var rows = applications.map(function (a) {
      var action = a.can_withdraw
        ? '<button type="button" class="btn btn-outline" data-withdraw="' + IL.esc(a.application_id) +
          '" data-title="' + IL.esc(a.title) + '">Withdraw</button>'
        : "";
      return "<tr>" +
        "<td><button type=\"button\" class=\"link-button\" data-opp-view=\"" + IL.esc(a.opportunity_id) + "\">" +
          IL.esc(a.title) + "</button><br><span class=\"muted\">" + IL.esc(a.company_name) + "</span></td>" +
        "<td>" + IL.esc(IL.formatDate(a.applied_at)) + "</td>" +
        "<td>" + IL.statusBadge(a.status, a.status_label) + "</td>" +
        "<td>" + action + "</td></tr>";
    }).join("");
    listBox.innerHTML = '<div class="dash-card table-wrap"><table>' +
      "<thead><tr><th>Opportunity</th><th>Applied</th><th>Status</th><th></th></tr></thead>" +
      "<tbody>" + rows + "</tbody></table></div>";
  }

  function load() {
    var ticket = ++requestCount;
    IL.hideAlert(listError);
    listBox.innerHTML = '<p class="muted">Loading your applications...</p>';
    IL.get("/api/applications")
      .then(function (data) {
        if (ticket !== requestCount) return;
        render(data.applications || []);
      })
      .catch(function (error) {
        if (ticket !== requestCount) return;
        listBox.innerHTML = "";
        IL.showAlert(listError, error.message);
        IL.invalidate("applications");     // try again next time the view is opened
      });
  }

  IL.views = IL.views || {};
  IL.views.applications = { load: load };

  // ------------------------------------------------------------------
  // Withdraw
  // ------------------------------------------------------------------
  listBox.addEventListener("click", function (event) {
    var button = event.target.closest("[data-withdraw]");
    if (!button) return;
    var title = button.getAttribute("data-title") || "this opportunity";
    if (!window.confirm("Withdraw your application for " + title + "? You cannot undo this.")) return;

    IL.setBusy(button, true, "Withdrawing...");
    IL.post("/api/applications/" + encodeURIComponent(button.getAttribute("data-withdraw")) + "/withdraw")
      .then(function () {
        IL.toast("Application withdrawn.", "success");
        IL.invalidate(["overview", "opportunities", "recommendations"]);
        load();
      })
      .catch(function (error) {
        IL.toast(error.message, "error");
        IL.setBusy(button, false);
      });
  });

  // ------------------------------------------------------------------
  // Apply dialog
  // ------------------------------------------------------------------
  IL.openApply = function (opportunityId, title) {
    applyingTo = opportunityId;
    applyForm.reset();
    IL.hideAlert(applyError);
    document.getElementById("apply-sub").textContent = title ? "You are applying for " + title + "." : "";
    IL.openModal("apply-modal");
  };

  // Any element with data-apply="<id>" (and optional data-title) starts an application.
  document.addEventListener("click", function (event) {
    var button = event.target.closest("[data-apply]");
    if (!button || button.disabled) return;
    IL.openApply(button.getAttribute("data-apply"), button.getAttribute("data-title"));
  });

  applyForm.addEventListener("submit", function (event) {
    event.preventDefault();
    if (!applyingTo) return;
    IL.hideAlert(applyError);

    var cover = applyCover.value.trim();
    if (cover.length > 2000) {
      IL.showAlert(applyError, "The cover note can be at most 2000 characters.");
      return;
    }

    IL.setBusy(applySubmit, true, "Sending...");
    IL.post("/api/applications", { opportunity_id: Number(applyingTo), cover_letter: cover })
      .then(function () {
        IL.closeModal("apply-modal");
        IL.closeModal("opp-modal");
        applyingTo = null;
        IL.toast("Application sent.", "success");
        IL.invalidate(["overview", "opportunities", "recommendations", "applications"]);
        if (window.location.hash === "#applications") {
          load();
        } else {
          window.location.hash = "#applications";     // opening the view loads the fresh list
        }
      })
      .catch(function (error) {
        IL.showAlert(applyError, error.message);
      })
      .finally(function () { IL.setBusy(applySubmit, false); });
  });
})();