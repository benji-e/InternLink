/* =====================================================================
   profile.js - "My profile": account details, editable fields, CV.

   Assumed endpoints (change here if your router.py differs):
     GET    /api/profile -> { profile: { full_name, email, phone, student_number, year_of_study, bio,
                                         university_name, department_name, programme_name,
                                         skills: [..], interests: [..], verified, completeness,
                                         cv: { filename, size, uploaded_at } | null } }
     PUT    /api/profile  body { phone, year_of_study, bio, skills: [names], interests: [names] }
     POST   /api/profile/cv   multipart field "cv"
     DELETE /api/profile/cv
   skills / interests may come back as plain strings or as objects with a  name.
   ===================================================================== */
(function () {
  "use strict";

  var PHONE_RE = /^\+?[0-9][0-9 \-]{6,18}[0-9]$/;
  var MAX_CV_BYTES = 5 * 1024 * 1024;
  var CV_EXTENSIONS = /\.(pdf|docx?)$/i;
  var MAX_LIST_ITEMS = 30;

  var errorBox = document.getElementById("profile-error");
  var form = document.getElementById("profile-form");
  var saveButton = document.getElementById("profile-save");
  var phoneInput = document.getElementById("profile-phone");
  var yearSelect = document.getElementById("profile-year");
  var bioInput = document.getElementById("profile-bio");
  var skillsInput = document.getElementById("profile-skills");
  var interestsInput = document.getElementById("profile-interests");
  var cvStatus = document.getElementById("cv-status");
  var cvFile = document.getElementById("cv-file");
  var cvUpload = document.getElementById("cv-upload");
  var cvDelete = document.getElementById("cv-delete");

  // ------------------------------------------------------------------
  // Helpers
  // ------------------------------------------------------------------
  function names(list) {
    return (list || []).map(function (item) {
      return typeof item === "string" ? item : (item && item.name) || "";
    }).filter(Boolean);
  }

  /** "Python, Excel,, python" -> ["Python", "Excel"]  (blank and repeated items removed). */
  function splitList(text) {
    var seen = {};
    var result = [];
    text.split(",").forEach(function (part) {
      var item = part.trim();
      var key = item.toLowerCase();
      if (item && !seen[key]) { seen[key] = true; result.push(item); }
    });
    return result;
  }

  function markInvalid(field, message) {
    IL.showAlert(errorBox, message);
    field.classList.add("is-invalid");
    field.focus();
    errorBox.scrollIntoView({ block: "nearest" });
  }

  form.addEventListener("input", function (event) { event.target.classList.remove("is-invalid"); });

  // ------------------------------------------------------------------
  // Show the profile
  // ------------------------------------------------------------------
  function account(label, value) {
    return "<dt>" + IL.esc(label) + "</dt><dd>" + IL.esc(value || "-") + "</dd>";
  }

  function showCv(cv) {
    if (cv && cv.filename) {
      cvStatus.textContent = cv.filename +
        (cv.size ? " (" + IL.formatBytes(cv.size) + ")" : "") +
        (cv.uploaded_at ? ", uploaded " + IL.timeAgo(cv.uploaded_at) : "");
      cvUpload.textContent = "Replace CV";
      cvUpload.dataset.label = "Replace CV";
      cvDelete.hidden = false;
    } else {
      cvStatus.textContent = "No CV uploaded yet.";
      cvUpload.textContent = "Upload CV";
      cvUpload.dataset.label = "Upload CV";
      cvDelete.hidden = true;
    }
  }

  function show(profile) {
    document.getElementById("profile-account").innerHTML =
      account("Name", profile.full_name) +
      account("Email", profile.email) +
      account("University", profile.university_name) +
      account("Department", profile.department_name) +
      account("Programme", profile.programme_name) +
      account("Student number", profile.student_number) +
      account("Status", profile.verified ? "Verified" : "Awaiting verification");

    var percent = Math.max(0, Math.min(100, Math.round(profile.completeness || 0)));
    document.getElementById("profile-bar").style.width = percent + "%";
    document.getElementById("profile-percent").textContent = percent + "% complete";

    phoneInput.value = profile.phone || "";
    yearSelect.value = String(profile.year_of_study || 1);
    bioInput.value = profile.bio || "";
    skillsInput.value = names(profile.skills).join(", ");
    interestsInput.value = names(profile.interests).join(", ");
    showCv(profile.cv);
  }

  function load() {
    IL.hideAlert(errorBox);
    IL.get("/api/profile")
      .then(function (data) { show(data.profile || {}); })
      .catch(function (error) {
        IL.showAlert(errorBox, error.message);
        IL.invalidate("profile");              // try again next time the view is opened
      });
  }

  IL.views = IL.views || {};
  IL.views.profile = { load: load };

  // ------------------------------------------------------------------
  // Save the details
  // ------------------------------------------------------------------
  form.addEventListener("submit", function (event) {
    event.preventDefault();
    IL.hideAlert(errorBox);
    IL.qsa(".is-invalid", form).forEach(function (el) { el.classList.remove("is-invalid"); });

    var phone = phoneInput.value.trim();
    var bio = bioInput.value.trim();
    var skills = splitList(skillsInput.value);
    var interests = splitList(interestsInput.value);

    if (phone && !PHONE_RE.test(phone)) return markInvalid(phoneInput, "Phone number is not valid. Example: +256 700 000000");
    if (bio.length > 1000) return markInvalid(bioInput, "About you can be at most 1000 characters.");
    if (skills.length > MAX_LIST_ITEMS) return markInvalid(skillsInput, "Please list at most " + MAX_LIST_ITEMS + " skills.");
    if (interests.length > MAX_LIST_ITEMS) return markInvalid(interestsInput, "Please list at most " + MAX_LIST_ITEMS + " interests.");

    IL.setBusy(saveButton, true, "Saving...");
    IL.put("/api/profile", {
      phone: phone,
      year_of_study: Number(yearSelect.value),
      bio: bio,
      skills: skills,
      interests: interests
    })
      .then(function () {
        IL.toast("Profile saved.", "success");
        IL.invalidate(["overview", "recommendations", "opportunities"]);   // matches depend on the profile
        load();
      })
      .catch(function (error) { IL.showAlert(errorBox, error.message); errorBox.scrollIntoView({ block: "nearest" }); })
      .finally(function () { IL.setBusy(saveButton, false); });
  });

  // ------------------------------------------------------------------
  // CV
  // ------------------------------------------------------------------
  cvUpload.addEventListener("click", function () {
    IL.hideAlert(errorBox);
    var file = cvFile.files && cvFile.files[0];
    if (!file) return markInvalid(cvFile, "Choose a CV file first.");
    if (!CV_EXTENSIONS.test(file.name)) return markInvalid(cvFile, "The CV must be a PDF, DOC or DOCX file.");
    if (file.size > MAX_CV_BYTES) return markInvalid(cvFile, "The CV is too large (" + IL.formatBytes(file.size) + "). The limit is 5 MB.");

    var data = new FormData();
    data.append("cv", file);

    IL.setBusy(cvUpload, true, "Uploading...");
    IL.upload("/api/profile/cv", data)
      .then(function () {
        cvFile.value = "";
        IL.toast("CV uploaded.", "success");
        IL.invalidate("overview");
        load();
      })
      .catch(function (error) { IL.showAlert(errorBox, error.message); })
      .finally(function () { IL.setBusy(cvUpload, false); });
  });

  cvDelete.addEventListener("click", function () {
    if (!window.confirm("Remove your CV? Companies will no longer see it on your applications.")) return;
    IL.setBusy(cvDelete, true, "Removing...");
    IL.del("/api/profile/cv")
      .then(function () {
        IL.toast("CV removed.", "success");
        IL.invalidate("overview");
        load();
      })
      .catch(function (error) { IL.showAlert(errorBox, error.message); })
      .finally(function () { IL.setBusy(cvDelete, false); });
  });
})();