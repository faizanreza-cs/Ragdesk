/*
 * ragdesk website widget. Add to any page:
 *   <script src="https://your-ragdesk-host/widget.js" data-api="https://your-ragdesk-host"
 *           data-title="Ask HR" defer></script>
 * No dependencies; styles are scoped to the widget's shadow DOM.
 */
(function () {
  var script = document.currentScript;
  var api = (script && script.dataset.api) || "";
  var title = (script && script.dataset.title) || "Ask the docs";

  var host = document.createElement("div");
  document.body.appendChild(host);
  var root = host.attachShadow({ mode: "open" });
  root.innerHTML =
    '<style>' +
    ':host{all:initial}' +
    '.btn{position:fixed;right:20px;bottom:20px;width:56px;height:56px;border-radius:50%;border:0;' +
    'background:#2a78d6;color:#fff;font:600 22px system-ui;cursor:pointer;box-shadow:0 4px 14px rgba(0,0,0,.2)}' +
    '.panel{position:fixed;right:20px;bottom:88px;width:min(380px,calc(100vw - 40px));height:520px;' +
    'background:#fff;color:#111;border-radius:14px;box-shadow:0 10px 40px rgba(0,0,0,.25);display:none;' +
    'flex-direction:column;font:14px/1.45 system-ui,sans-serif;overflow:hidden}' +
    '.panel.open{display:flex}' +
    '.head{padding:12px 16px;background:#2a78d6;color:#fff;font-weight:600}' +
    '.log{flex:1;overflow:auto;padding:12px 14px;display:flex;flex-direction:column;gap:10px}' +
    '.m{padding:8px 11px;border-radius:10px;max-width:88%;white-space:pre-wrap}' +
    '.u{align-self:flex-end;background:#e8f0fb}.b{align-self:flex-start;background:#f3f3f1}' +
    '.src{font-size:12px;color:#555;margin-top:6px}' +
    'form{display:flex;border-top:1px solid #eee}' +
    'input{flex:1;border:0;padding:12px 14px;font:inherit;outline:none}' +
    'button.send{border:0;background:none;color:#2a78d6;font-weight:600;padding:0 14px;cursor:pointer}' +
    '</style>' +
    '<button class="btn" aria-label="Open chat">?</button>' +
    '<div class="panel" role="dialog">' +
    '<div class="head"></div><div class="log" aria-live="polite"></div>' +
    '<form><input placeholder="Ask a question..." aria-label="Question" maxlength="1000">' +
    '<button class="send" type="submit">Send</button></form></div>';

  var btn = root.querySelector(".btn"), panel = root.querySelector(".panel");
  var log = root.querySelector(".log"), form = root.querySelector("form");
  var input = root.querySelector("input");
  root.querySelector(".head").textContent = title;
  panel.setAttribute("aria-label", title);

  btn.addEventListener("click", function () {
    panel.classList.toggle("open");
    if (panel.classList.contains("open")) input.focus();
  });

  function add(cls, text, sources) {
    var div = document.createElement("div");
    div.className = "m " + cls;
    div.textContent = text;
    if (sources && sources.length) {
      var s = document.createElement("div");
      s.className = "src";
      s.textContent = "Sources: " + sources.map(function (c) {
        return "[" + c.n + "] " + c.source.split("/").pop() + " › " + c.section;
      }).join(" · ");
      div.appendChild(s);
    }
    log.appendChild(div);
    log.scrollTop = log.scrollHeight;
    return div;
  }

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var q = input.value.trim();
    if (!q) return;
    input.value = "";
    add("u", q);
    var pending = add("b", "…");
    fetch(api + "/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: q })
    })
      .then(function (r) { if (!r.ok) throw r; return r.json(); })
      .then(function (d) { pending.remove(); add("b", d.answer, d.citations); })
      .catch(function () { pending.textContent = "Sorry, something went wrong."; });
  });
})();
