/* =====================================================================
   index.js - home page: login and sign-up dialogs.
   Needs api.js (IL) and the element ids in index.html.
   ===================================================================== */
(function () {
  "use strict";

  var DASHBOARD_URL = "/dashboard.html";

  // ---- Page elements ----
  var loginForm = document.getElementById("login-form");
  var loginError = document.getElementById("login-error");
  var loginSubmit = document.getElementById("login-submit");

  var signupForm = document.getElementById("signup-form");
  var signupError = document.getElementById("signup-error");
  var signupSubmit = document.getElementById("signup-submit");
  var universitySelect = document.getElementById("signup-university");
  var departmentSelect = document.getElementById("signup-department");
  var programmeSelect = document.getElementById("signup-programme");
  var emailInput = document.getElementById("signup-email");
  var emailHint = document.getElementById("signup-email-hint");
  var banner = document.getElementById("verify-banner");

  var universities = [];            // loaded once from the server
  var universitiesState = "idle";   // idle | loading | loaded
  var departmentRequest = 0;        // protects against slow answers arriving out of order
  var programmeRequest = 0;

  // ------------------------------------------------------------------
  // Helpers
  // ------------------------------------------------------------------
  function fillSelect(select, placeholder, items, valueKey, labelKey) {
    select.innerHTML = "";
    var first = document.createElement("option");
    first.value = "";
    first.textContent = placeholder;
    select.appendChild(first);
    items.forEach(function (item) {
      var option = document.createElement("option");
      option.value = item[valueKey];
      option.textContent = item[labelKey];       // textContent: safe even if the name contains < or &
      select.appendChild(option);
    });
  }

  function resetSelect(select, placeholder) {
    fillSelect(select, placeholder, [], "", "");
    select.disabled = true;
  }

  function selectedUniversity() {
    var id = Number(universitySelect.value);
    for (var i = 0; i < universities.length; i++) {
      if (universities[i].university_id === id) return universities[i];
    }
    return null;
  }

  function showBanner(kind, message) {
    banner.className = "alert mt-2 alert-" + kind;
    banner.textContent = message;
    banner.hidden = false;
  }

  function clearInvalid(form) {
    IL.qsa(".is-invalid", form).forEach(function (el) { el.classList.remove("is-invalid"); });
  }

  /** Show an error at the top of a dialog and mark the field that caused it. */
  function failField(alertBox, field, message) {
    IL.showAlert(alertBox, message);
    if (field) {
      field.classList.add("is-invalid");
      field.focus();
    }
    var overlay = alertBox.closest(".modal-overlay");
    if (overlay) overlay.scrollTop = 0;
    return false;
  }

  // Remove the red border as soon as the person edits the field.
  [loginForm, signupForm].forEach(function (form) {
    form.addEventListener("input", function (event) {
      event.target.classList.remove("is-invalid");
    });
    form.addEventListener("change", function (event) {
      event.target.classList.remove("is-invalid");
    });
  });

  // ------------------------------------------------------------------
  // Opening, closing and switching dialogs
  // ------------------------------------------------------------------
  function openDialog(name) {
    if (name === "login") {
      IL.hideAlert(loginError);
      IL.openModal("login-modal");
    } else if (name === "signup") {
      IL.hideAlert(signupError);
      IL.openModal("signup-modal");
      loadUniversities();
    }
  }

  document.addEventListener("click", function (event) {
    var opener = event.target.closest("[data-open]");
    if (opener) {
      openDialog(opener.getAttribute("data-open"));
      return;
    }
    var switcher = event.target.closest("[data-switch]");
    if (switcher) {
      var target = switcher.getAttribute("data-switch");
      IL.closeModal(switcher.closest(".modal-overlay"));
      openDialog(target);
    }
  });

  // ------------------------------------------------------------------
  // Sign-up: university -> department -> programme
  // ------------------------------------------------------------------
  function loadUniversities() {
    if (universitiesState !== "idle") return;
    universitiesState = "loading";
    IL.get("/api/meta/universities", null, { noRedirect: true })
      .then(function (data) {
        universities = data.universities || [];
        universitiesState = "loaded";
        if (!universities.length) {
          fillSelect(universitySelect, "No universities are registered yet", [], "", "");
          IL.showAlert(signupError, "No universities are registered on InternLink yet, so sign-up is not possible right now.");
          return;
        }
        fillSelect(universitySelect, "Choose your university", universities, "university_id", "name");
      })
      .catch(function (error) {
        universitiesState = "idle";                       // allow another try next time the dialog opens
        fillSelect(universitySelect, "Could not load universities", [], "", "");
        IL.showAlert(signupError, error.message);
      });
  }

  universitySelect.addEventListener("change", function () {
    var university = selectedUniversity();
    resetSelect(departmentSelect, "Choose a university first");
    resetSelect(programmeSelect, "Choose a department first");

    if (!university) {
      emailHint.textContent = "Choose your university first to see which email address is accepted.";
      return;
    }
    emailHint.textContent = "Use your university email, ending in @" + university.email_domain +
      " (addresses like @std." + university.email_domain + " also work).";

    var ticket = ++departmentRequest;
    departmentSelect.innerHTML = '<option value="">Loading...</option>';
    IL.get("/api/meta/departments", { university_id: university.university_id }, { noRedirect: true })
      .then(function (data) {
        if (ticket !== departmentRequest) return;         // the person already chose something else
        var list = data.departments || [];
        fillSelect(departmentSelect, list.length ? "Choose your department" : "No departments listed", list, "department_id", "name");
        departmentSelect.disabled = !list.length;
      })
      .catch(function (error) {
        if (ticket !== departmentRequest) return;
        resetSelect(departmentSelect, "Could not load departments");
        IL.showAlert(signupError, error.message);
      });
  });

  departmentSelect.addEventListener("change", function () {
    resetSelect(programmeSelect, "Choose a department first");
    var departmentId = departmentSelect.value;
    if (!departmentId) return;

    var ticket = ++programmeRequest;
    programmeSelect.innerHTML = '<option value="">Loading...</option>';
    IL.get("/api/meta/programmes", { department_id: departmentId }, { noRedirect: true })
      .then(function (data) {
        if (ticket !== programmeRequest) return;
        var list = data.programmes || [];
        fillSelect(programmeSelect, list.length ? "Choose your programme" : "No programmes listed", list, "programme_id", "name");
        programmeSelect.disabled = !list.length;
      })
      .catch(function (error) {
        if (ticket !== programmeRequest) return;
        resetSelect(programmeSelect, "Could not load programmes");
        IL.showAlert(signupError, error.message);
      });
  });

  // ------------------------------------------------------------------
  // Sign-up: check, send
  // ------------------------------------------------------------------
  var EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
  var PHONE_RE = /^\+?[0-9][0-9 \-]{6,18}[0-9]$/;
  var STUDENT_NUMBER_RE = /^[A-Za-z0-9\/\-_. ]+$/;

  function field(id) { return document.getElementById(id); }

  /** Returns the data to send, or null after showing the first problem found. */
  function readSignupForm() {
    IL.hideAlert(signupError);
    clearInvalid(signupForm);

    var name = field("signup-name").value.trim();
    var phone = field("signup-phone").value.trim();
    var studentNumber = field("signup-student-number").value.trim();
    var year = field("signup-year").value;
    var email = emailInput.value.trim().toLowerCase();
    var password = field("signup-password").value;
    var confirm = field("signup-confirm").value;
    var university = selectedUniversity();

    if (name.length < 2) return failField(signupError, field("signup-name"), "Please enter your full name.") || null;
    if (phone && !PHONE_RE.test(phone)) return failField(signupError, field("signup-phone"), "Phone number is not valid. Example: +256 700 000000") || null;
    if (!university) return failField(signupError, universitySelect, "Please choose your university.") || null;
    if (!departmentSelect.value) return failField(signupError, departmentSelect, "Please choose your department.") || null;
    if (!programmeSelect.value) return failField(signupError, programmeSelect, "Please choose your programme.") || null;
    if (!studentNumber) return failField(signupError, field("signup-student-number"), "Please enter your student number.") || null;
    if (!STUDENT_NUMBER_RE.test(studentNumber)) {
      return failField(signupError, field("signup-student-number"), "Student number can only contain letters, numbers, / - _ . and spaces.") || null;
    }
    if (!year) return failField(signupError, field("signup-year"), "Please choose your year of study.") || null;
    if (!EMAIL_RE.test(email)) return failField(signupError, emailInput, "Please enter a valid email address.") || null;

    var domain = email.split("@")[1];
    var base = university.email_domain.toLowerCase();
    if (domain !== base && !domain.endsWith("." + base)) {
      return failField(signupError, emailInput, "Please use your university email address (ending in @" + university.email_domain + ").") || null;
    }

    if (password.length < 8) return failField(signupError, field("signup-password"), "Password must be at least 8 characters.") || null;
    if (!/[A-Za-z]/.test(password) || !/\d/.test(password)) {
      return failField(signupError, field("signup-password"), "Password must contain at least one letter and one number.") || null;
    }
    if (password !== confirm) return failField(signupError, field("signup-confirm"), "The two passwords do not match.") || null;

    return {
      full_name: name,
      phone: phone,
      email: email,
      password: password,
      student_number: studentNumber,
      year_of_study: Number(year),
      university_id: university.university_id,
      department_id: Number(departmentSelect.value),
      programme_id: Number(programmeSelect.value)
    };
  }

  signupForm.addEventListener("submit", function (event) {
    event.preventDefault();
    var payload = readSignupForm();
    if (!payload) return;

    IL.setBusy(signupSubmit, true, "Creating account...");
    IL.post("/api/auth/signup", payload, { noRedirect: true })
      .then(function (data) {
        signupForm.reset();
        resetSelect(departmentSelect, "Choose a university first");
        resetSelect(programmeSelect, "Choose a department first");
        emailHint.textContent = "Choose your university first to see which email address is accepted.";
        IL.closeModal("signup-modal");

        if (data.verification_required) {
          showBanner("info", "Account created. We sent a verification link to " + data.email +
            ". Open it, then log in.");
        } else {
          IL.toast("Account created. Please log in.", "success");
        }
        field("login-email").value = data.email || payload.email;
        field("login-password").value = "";
        openDialog("login");
        field("login-password").focus();
      })
      .catch(function (error) {
        IL.showAlert(signupError, error.message);
        signupError.closest(".modal-overlay").scrollTop = 0;
      })
      .finally(function () { IL.setBusy(signupSubmit, false); });
  });

  // ------------------------------------------------------------------
  // Login
  // ------------------------------------------------------------------
  loginForm.addEventListener("submit", function (event) {
    event.preventDefault();
    IL.hideAlert(loginError);
    clearInvalid(loginForm);

    var emailField = field("login-email");
    var passwordField = field("login-password");
    var email = emailField.value.trim().toLowerCase();
    var password = passwordField.value;

    if (!email) return failField(loginError, emailField, "Please enter your email address.");
    if (!password) return failField(loginError, passwordField, "Please enter your password.");

    IL.setBusy(loginSubmit, true, "Logging in...");
    IL.post("/api/auth/login", { email: email, password: password }, { noRedirect: true })
      .then(function () {
        window.location.href = DASHBOARD_URL;
      })
      .catch(function (error) {
        passwordField.value = "";
        IL.showAlert(loginError, error.message);
        IL.setBusy(loginSubmit, false);
        passwordField.focus();
      });
  });

  // ------------------------------------------------------------------
  // When the page opens
  // ------------------------------------------------------------------
  // 1. Messages from the address (?verified=1, ?verified=0, ?expired=1)
  var params = new URLSearchParams(window.location.search);
  if (params.get("verified") === "1") {
    showBanner("success", "Your email address is verified. You can now log in.");
    openDialog("login");
  } else if (params.get("verified") === "0") {
    showBanner("error", "That verification link is invalid or has expired. Please sign up again or contact support.");
  } else if (params.get("expired") === "1") {
    showBanner("info", "Your session has ended. Please log in again.");
    openDialog("login");
  }
  if (params.has("verified") || params.has("expired")) {
    window.history.replaceState({}, document.title, window.location.pathname);   // tidy the address bar
  }

  // 2. If the student is already logged in, replace the buttons with a link to the dashboard.
  IL.get("/api/auth/me", null, { noRedirect: true })
    .then(function (data) {
      var name = (data.user && data.user.full_name) ? data.user.full_name.split(" ")[0] : "";
      var nav = IL.qs(".nav-actions");
      if (nav) {
        nav.innerHTML = '<a class="btn btn-primary" href="' + DASHBOARD_URL + '">' +
          (name ? "Open dashboard (" + IL.esc(name) + ")" : "Open dashboard") + "</a>";
      }
      var hero = IL.qs(".hero-actions");
      if (hero) {
        hero.innerHTML = '<a class="btn btn-accent btn-lg" href="' + DASHBOARD_URL + '">Go to my dashboard</a>';
      }
    })
    .catch(function () { /* not logged in: keep the normal buttons */ });
})();