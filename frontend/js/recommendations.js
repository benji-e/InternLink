/* =====================================================================
   recommendations.js - "Recommended for you": opportunities ranked by
   how well they match the student, with matched and missing skills.

   Assumed endpoint (change here if your router.py differs):
     GET /api/recommendations?limit=
         -> { recommendations: [ {opportunity_id, title, company_name, location, sector, duration,
                                  deadline, days_left, match_score, already_applied,
                                  matched_skills: [..], missing_skills: [..]} ] }
   Needs opportunities.js (IL.renderOpportunityCard).
   ===================================================================== */
(function () {
  "use strict";

  var listBox = document.getElementById("rec-list");
  var errorBox = document.getElementById("rec-error");
  var requestCount = 0;

  function skillName(skill) {
    return typeof skill === "string" ? skill : (skill && skill.name) || "";
  }

  function chips(label, skills, extraClass) {
    var names = (skills || []).map(skillName).filter(Boolean);
    if (!names.length) return "";
    return '<div><div class="muted">' + IL.esc(label) + '</div><div class="chips">' +
      names.map(function (name) {
        return '<span class="chip ' + extraClass + '">' + IL.esc(name) + "</span>";
      }).join("") + "</div></div>";
  }

  function skillDetails(item) {
    return chips("Skills you have", item.matched_skills, "") +
           chips("Skills to build", item.missing_skills, "chip-missing");
  }

  function load() {
    var ticket = ++requestCount;
    IL.hideAlert(errorBox);
    listBox.innerHTML = '<p class="muted">Finding your best matches...</p>';

    IL.get("/api/recommendations")
      .then(function (data) {
        if (ticket !== requestCount) return;
        var items = data.recommendations || [];
        listBox.innerHTML = items.length
          ? items.map(function (item) {
              return IL.renderOpportunityCard(item, skillDetails(item));
            }).join("")
          : '<div class="dash-card empty"><p>No matches yet.</p>' +
            '<p class="muted">Add your skills and interests to your profile so we can find opportunities that fit.</p>' +
            '<a class="btn btn-primary" href="#profile">Update my profile</a></div>';
      })
      .catch(function (error) {
        if (ticket !== requestCount) return;
        listBox.innerHTML = "";
        IL.showAlert(errorBox, error.message);
        IL.invalidate("recommendations");      // try again next time the view is opened
      });
  }

  IL.views = IL.views || {};
  IL.views.recommendations = { load: load };
})();