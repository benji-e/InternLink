/* =====================================================================
   api.js - shared helpers for every InternLink student page.
   Loaded first; everything is exposed on the global object  IL.

   Talking to the backend (all return a Promise of the parsed JSON):
     IL.get("/api/opportunities", { q: "python", page: 2 })
     IL.post("/api/auth/login", { email, password }, { noRedirect: true })
     IL.put("/api/profile", { phone: "..." })
     IL.del("/api/profile/cv")
     IL.upload("/api/profile/cv", formData)
   On failure they throw an IL.ApiError with .status and .message.
   ===================================================================== */
(function () {
  "use strict";

  var CSRF_HEADER = "X-Requested-With";   // must match router.py
  var CSRF_VALUE = "InternLink";
  var HOME_PAGE = "/index.html";
  var TIMEOUT_MS = 30000;

  var IL = {};

  // ------------------------------------------------------------------
  // Errors
  // ------------------------------------------------------------------
  function ApiError(status, message, details) {
    this.name = "ApiError";
    this.status = status;
    this.message = message;
    this.details = details || null;
  }
  ApiError.prototype = Object.create(Error.prototype);
  ApiError.prototype.constructor = ApiError;
  IL.ApiError = ApiError;

  // ------------------------------------------------------------------
  // Backend calls
  // ------------------------------------------------------------------
  function buildUrl(path, query) {
    if (!query) return path;
    var params = new URLSearchParams();
    Object.keys(query).forEach(function (key) {
      var value = query[key];
      if (value === undefined || value === null || value === "" || value === false) return;
      params.set(key, value === true ? "1" : String(value));
    });
    var text = params.toString();
    return text ? path + "?" + text : path;
  }

  /**
   * options.body       object, sent as JSON
   * options.formData   FormData, sent as multipart (for uploads)
   * options.query      object, added to the address as ?a=1&b=2
   * options.noRedirect true = do NOT go to the home page on a 401 (used by login)
   */
  IL.request = function (method, path, options) {
    options = options || {};
    var headers = {};
    headers[CSRF_HEADER] = CSRF_VALUE;
    headers["Accept"] = "application/json";

    var init = { method: method, headers: headers, credentials: "same-origin" };
    if (options.formData) {
      init.body = options.formData;                       // the browser sets the multipart boundary itself
    } else if (options.body !== undefined) {
      headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(options.body);
    }

    var controller = new AbortController();
    init.signal = controller.signal;
    var timer = setTimeout(function () { controller.abort(); }, TIMEOUT_MS);

    return fetch(buildUrl(path, options.query), init)
      .then(function (response) {
        return response.text().then(function (text) {
          var data = {};
          if (text) {
            try { data = JSON.parse(text); } catch (e) { data = {}; }
          }
          if (!response.ok) {
            if (response.status === 401 && !options.noRedirect) {
              window.location.href = HOME_PAGE + "?expired=1";
            }
            throw new ApiError(
              response.status,
              data.error || "Something went wrong (error " + response.status + ").",
              data.details
            );
          }
          return data;
        });
      })
      .catch(function (error) {
        if (error instanceof ApiError) throw error;
        if (error && error.name === "AbortError") {
          throw new ApiError(0, "The server took too long to answer. Please try again.");
        }
        throw new ApiError(0, "Cannot reach the server. Check your connection and try again.");
      })
      .finally(function () { clearTimeout(timer); });
  };

  IL.get = function (path, query, options) {
    return IL.request("GET", path, Object.assign({}, options, { query: query }));
  };
  IL.post = function (path, body, options) {
    return IL.request("POST", path, Object.assign({}, options, { body: body === undefined ? {} : body }));
  };
  IL.put = function (path, body, options) {
    return IL.request("PUT", path, Object.assign({}, options, { body: body === undefined ? {} : body }));
  };
  IL.del = function (path, options) {
    return IL.request("DELETE", path, options);
  };
  IL.upload = function (path, formData, options) {
    return IL.request("POST", path, Object.assign({}, options, { formData: formData }));
  };

  // ------------------------------------------------------------------
  // Safe HTML
  // ------------------------------------------------------------------
  var ESCAPES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };

  /** Always use this when putting text from the server or the user into innerHTML. */
  IL.esc = function (value) {
    if (value === null || value === undefined) return "";
    return String(value).replace(/[&<>"']/g, function (ch) { return ESCAPES[ch]; });
  };

  IL.qs = function (selector, root) { return (root || document).querySelector(selector); };
  IL.qsa = function (selector, root) {
    return Array.prototype.slice.call((root || document).querySelectorAll(selector));
  };

  // ------------------------------------------------------------------
  // Dates and numbers
  // ------------------------------------------------------------------
  /** Date-only values (YYYY-MM-DD) are read as LOCAL dates so they never shift by a day. */
  IL.parseDate = function (value) {
    if (!value) return null;
    var match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
    var date = match
      ? new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]))
      : new Date(value);
    return isNaN(date.getTime()) ? null : date;
  };

  IL.formatDate = function (value) {
    var date = IL.parseDate(value);
    return date ? date.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" }) : "-";
  };

  IL.formatDateTime = function (value) {
    var date = IL.parseDate(value);
    return date
      ? date.toLocaleString("en-GB", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" })
      : "-";
  };

  IL.timeAgo = function (value) {
    var date = IL.parseDate(value);
    if (!date) return "-";
    var seconds = Math.round((Date.now() - date.getTime()) / 1000);
    if (seconds < 60) return "just now";
    if (seconds < 3600) return Math.floor(seconds / 60) + " min ago";
    if (seconds < 86400) return Math.floor(seconds / 3600) + " h ago";
    if (seconds < 86400 * 7) return Math.floor(seconds / 86400) + " day(s) ago";
    return IL.formatDate(value);
  };

  IL.formatBytes = function (bytes) {
    if (!bytes && bytes !== 0) return "";
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1048576) return Math.round(bytes / 1024) + " KB";
    return (bytes / 1048576).toFixed(1) + " MB";
  };

  IL.formatScore = function (score) {
    return score === null || score === undefined ? "-" : Math.round(score) + "%";
  };

  /** CSS class for a match score pill: match-high (70+), match-mid (40+), match-low. */
  IL.matchClass = function (score) {
    if (score >= 70) return "match-high";
    if (score >= 40) return "match-mid";
    return "match-low";
  };

  /** Text and CSS class for the days left until a deadline. */
  IL.daysLeft = function (days) {
    if (days === null || days === undefined) return { text: "", cls: "" };
    if (days < 0) return { text: "Closed", cls: "deadline-soon" };
    if (days === 0) return { text: "Last day to apply", cls: "deadline-soon" };
    if (days === 1) return { text: "1 day left", cls: "deadline-soon" };
    return { text: days + " days left", cls: days <= 3 ? "deadline-soon" : "" };
  };

  /** A coloured status badge. label comes from the server (status_label). */
  IL.statusBadge = function (status, label) {
    return '<span class="badge badge-' + IL.esc(status) + '">' + IL.esc(label || status) + "</span>";
  };

  IL.debounce = function (fn, wait) {
    var timer;
    return function () {
      var args = arguments, self = this;
      clearTimeout(timer);
      timer = setTimeout(function () { fn.apply(self, args); }, wait);
    };
  };

  // ------------------------------------------------------------------
  // Messages and buttons
  // ------------------------------------------------------------------
  /** A small message in the corner. type: "success", "error" or nothing. */
  IL.toast = function (message, type) {
    var container = document.getElementById("toast-container");
    if (!container) {
      container = document.createElement("div");
      container.id = "toast-container";
      container.className = "toast-container";
      container.setAttribute("aria-live", "polite");
      document.body.appendChild(container);
    }
    var toast = document.createElement("div");
    toast.className = "toast" + (type ? " toast-" + type : "");
    toast.textContent = message;                          // textContent: never interpreted as HTML
    container.appendChild(toast);
    setTimeout(function () { toast.remove(); }, type === "error" ? 7000 : 4000);
  };

  /** Show a message inside an .alert element (use the same element for every message). */
  IL.showAlert = function (element, message) {
    if (!element) return;
    element.textContent = message;
    element.hidden = false;
  };
  IL.hideAlert = function (element) {
    if (!element) return;
    element.hidden = true;
    element.textContent = "";
  };

  /** Disable a button and show text like "Saving..." while a request runs. */
  IL.setBusy = function (button, busy, busyText) {
    if (!button) return;
    if (busy) {
      if (button.dataset.label === undefined) button.dataset.label = button.textContent;
      button.disabled = true;
      button.textContent = busyText || "Please wait...";
    } else {
      button.disabled = false;
      if (button.dataset.label !== undefined) {
        button.textContent = button.dataset.label;
        delete button.dataset.label;
      }
    }
  };

  // ------------------------------------------------------------------
  // Dialogs (modal overlays)
  // ------------------------------------------------------------------
  var lastFocus = null;

  function visibleModals() {
    return IL.qsa(".modal-overlay").filter(function (m) { return !m.hidden; });
  }

  IL.openModal = function (id) {
    var overlay = document.getElementById(id);
    if (!overlay) return;
    if (!visibleModals().length) lastFocus = document.activeElement;
    overlay.hidden = false;
    document.body.style.overflow = "hidden";
    var target = overlay.querySelector("input:not([type=hidden]):not([disabled]), select:not([disabled]), textarea, button.btn");
    if (target) target.focus();
  };

  IL.closeModal = function (idOrElement) {
    var overlay = typeof idOrElement === "string" ? document.getElementById(idOrElement) : idOrElement;
    if (!overlay) return;
    overlay.hidden = true;
    if (!visibleModals().length) {
      document.body.style.overflow = "";
      if (lastFocus && lastFocus.focus) lastFocus.focus();
      lastFocus = null;
    }
  };

  // Shared behaviour for every dialog on every page:
  //  - any element with [data-close] closes its dialog
  //  - clicking the dark area outside the dialog closes it
  //  - the Escape key closes the top dialog
  var pressedOnOverlay = false;
  document.addEventListener("mousedown", function (event) {
    pressedOnOverlay = event.target.classList && event.target.classList.contains("modal-overlay");
  });
  document.addEventListener("click", function (event) {
    var closer = event.target.closest && event.target.closest("[data-close]");
    if (closer) {
      IL.closeModal(closer.closest(".modal-overlay"));
      return;
    }
    if (pressedOnOverlay && event.target.classList && event.target.classList.contains("modal-overlay")) {
      IL.closeModal(event.target);
    }
  });
  document.addEventListener("keydown", function (event) {
    if (event.key !== "Escape") return;
    var open = visibleModals();
    if (open.length) IL.closeModal(open[open.length - 1]);
  });

  window.IL = IL;
})();