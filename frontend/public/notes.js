// Observations: a "Noter" button for any app on the tailnet. One tag embeds it:
//   <script src="http://100.127.215.65:8096/notes.js" data-app="Books"></script>
// A copy the app serves itself names the service's origin instead: data-endpoint="http://100.127.215.65:8096".
// The note goes to firstmate with the app's name and the page it was written on.
(function () {
  "use strict";
  var me = document.currentScript || document.querySelector('script[src*="/notes.js"][data-app]');
  if (!me || window.shipNotes) return;
  window.shipNotes = true;

  var app = me.getAttribute("data-app") || location.host;
  var endpoint = new URL("/note", me.getAttribute("data-endpoint") || me.src).href;
  var key = "ship-notes:" + app;
  var draft = load();  // {text, id}: the id stays with the text, so a retry is never a second note

  var css =
    ":host{all:initial}" +
    "*{box-sizing:border-box;font-family:-apple-system,BlinkMacSystemFont,'SF Pro Text','Segoe UI',system-ui,sans-serif}" +
    "[hidden]{display:none!important}" +
    ".pill,.sheet{position:fixed;z-index:2147483647;right:max(16px,env(safe-area-inset-right))}" +
    ".pill{bottom:max(16px,env(safe-area-inset-bottom));border:0;border-radius:999px;padding:0 16px;height:40px;" +
    "font-size:14px;font-weight:500;color:#fff;background:rgba(29,29,31,.62);cursor:pointer;opacity:.75;" +
    "-webkit-backdrop-filter:blur(10px);backdrop-filter:blur(10px);box-shadow:0 2px 10px rgba(0,0,0,.16);" +
    "transition:opacity .15s}" +
    ".pill:hover,.pill:focus-visible{opacity:1}" +
    ".sheet{bottom:16px;width:360px;max-width:calc(100vw - 32px);padding:12px;border-radius:18px;" +
    "background:#fff;color:#1d1d1f;box-shadow:0 14px 44px rgba(0,0,0,.2),0 0 0 1px rgba(0,0,0,.06)}" +
    "textarea{display:block;width:100%;min-height:128px;padding:6px;border:0;outline:0;resize:none;" +
    "background:transparent;color:inherit;font-size:16px;line-height:1.45}" +
    "textarea::placeholder{color:#a1a1a6}" +
    ".row{display:flex;align-items:center;gap:12px;margin-top:8px}" +
    ".say{flex:1;min-width:0;padding-left:6px;font-size:13px;color:#6e6e73}" +
    ".send{border:0;border-radius:999px;padding:0 18px;height:40px;font-size:15px;font-weight:600;" +
    "color:#fff;background:#0a62d0;cursor:pointer}" +
    ".send:disabled{opacity:.35;cursor:default}" +
    ".done{padding:52px 0;text-align:center;font-size:16px;font-weight:600}" +
    "@media (max-width:520px){.sheet{left:8px;right:8px;bottom:8px;width:auto;max-width:none;" +
    "padding-bottom:max(12px,env(safe-area-inset-bottom))}textarea{min-height:150px}}" +
    "@media (prefers-color-scheme:dark){.pill{color:#1d1d1f;background:rgba(242,242,243,.8)}" +
    ".sheet{background:#1c1c1f;color:#f2f2f3;box-shadow:0 14px 44px rgba(0,0,0,.5),0 0 0 1px rgba(255,255,255,.08)}" +
    "textarea::placeholder{color:#6a6a70}.say{color:#9a9aa1}.send{color:#0b0b0c;background:#5aa7ff}}" +
    "@media print{.pill,.sheet{display:none!important}}";

  var host = document.createElement("div");
  var root = host.attachShadow({ mode: "open" });
  try {
    var sheet = new CSSStyleSheet();
    sheet.replaceSync(css);  // a constructed sheet passes a page's style-src policy
    root.adoptedStyleSheets = [sheet];
  } catch (e) {
    var style = document.createElement("style");
    style.textContent = css;
    root.appendChild(style);
  }

  var pill = make("button", "pill", "Noter");
  var panel = make("div", "sheet");
  panel.setAttribute("role", "dialog");
  panel.setAttribute("aria-label", "Observation");
  panel.hidden = true;
  var form = make("div");
  var box = make("textarea");
  box.placeholder = "Une observation…";
  box.maxLength = 4000;
  box.setAttribute("aria-label", "Observation");
  var row = make("div", "row");
  var say = make("span", "say");
  say.setAttribute("aria-live", "polite");
  var send = make("button", "send", "Envoyer");
  var done = make("div", "done", "Envoyé à firstmate");
  done.hidden = true;
  row.append(say, send);
  form.append(box, row);
  panel.append(form, done);
  root.append(pill, panel);

  var busy = false;
  var closing = 0;

  pill.addEventListener("click", open);
  send.addEventListener("click", submit);
  box.addEventListener("input", function () {
    draft = { text: box.value, id: "" };
    keep();
    say.textContent = "";
    ready();
  });
  box.addEventListener("keydown", function (event) {
    if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) submit();
  });
  panel.addEventListener("keydown", function (event) {
    if (event.key === "Escape") close();
  });
  document.addEventListener("pointerdown", function (event) {
    if (!panel.hidden && event.composedPath().indexOf(host) < 0) close();
  }, true);
  if (window.visualViewport) {
    // Keep the sheet above a phone's keyboard.
    visualViewport.addEventListener("resize", lift);
    visualViewport.addEventListener("scroll", lift);
  }

  function open() {
    clearTimeout(closing);
    box.value = draft.text || "";
    say.textContent = "";
    form.hidden = false;
    done.hidden = true;
    pill.hidden = true;
    panel.hidden = false;
    ready();
    lift();
    box.focus();
  }

  function close() {
    clearTimeout(closing);
    panel.hidden = true;
    pill.hidden = false;
  }

  function ready() {
    box.readOnly = busy;  // what is typed during a send would be lost when it succeeds
    send.disabled = busy || !box.value.trim();
  }

  function lift() {
    var view = window.visualViewport;
    var hidden = view ? Math.max(0, innerHeight - view.height - view.offsetTop) : 0;
    panel.style.transform = hidden ? "translateY(-" + hidden + "px)" : "";
  }

  function submit() {
    var text = box.value.trim();
    if (busy || !text) return;
    if (!draft.id) draft = { text: box.value, id: newId() };
    keep();
    busy = true;
    ready();
    say.textContent = "Envoi…";
    fetch(endpoint, {
      method: "POST",
      mode: "cors",
      credentials: "omit",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ app: app, page: location.href, text: text, device: navigator.userAgent,
                             request_id: draft.id })
    }).then(function (response) {
      if (response.status === 202) return sent();
      say.textContent = response.status === 429 ? "Trop de notes, plus tard"
        : response.status === 503 ? "Pas encore transmis. Réessayer ?" : "Pas envoyé. Réessayer ?";
    }, function () {
      say.textContent = "Pas envoyé. Réessayer ?";
    }).then(function () {
      busy = false;
      ready();
    });
  }

  function sent() {
    draft = {};
    keep();
    box.value = "";
    say.textContent = "";
    form.hidden = true;
    done.hidden = false;
    closing = setTimeout(close, 1400);
  }

  function load() {
    try {
      return JSON.parse(localStorage.getItem(key)) || {};
    } catch (e) {
      return {};
    }
  }

  function keep() {
    try {
      if (draft.text) localStorage.setItem(key, JSON.stringify(draft));
      else localStorage.removeItem(key);
    } catch (e) { /* private window: the draft lives as long as the page */ }
  }

  function newId() {
    var bytes = new Uint8Array(12);
    crypto.getRandomValues(bytes);  // randomUUID needs https; the tailnet is plain http
    return Array.prototype.map.call(bytes, function (b) { return (b + 256).toString(16).slice(1); }).join("");
  }

  function make(tag, name, text) {
    var element = document.createElement(tag);
    if (name) element.className = name;
    if (text) element.textContent = text;
    return element;
  }

  function attach() {
    document.body.appendChild(host);
  }
  if (document.body) attach();
  else document.addEventListener("DOMContentLoaded", attach);
})();
