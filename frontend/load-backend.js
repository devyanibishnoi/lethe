// Picks the real backend (app.js, real fetch() calls to FastAPI/Postgres) or
// the mock one (mock.js, canned data + sessionStorage, zero backend) and
// loads it with document.write so it's available before this page's own
// inline script runs, same as a plain <script src> tag would be.
//
// Priority: explicit ?backend=mock|real in the URL (also remembered in
// localStorage so it sticks across page navigation) > a previously
// remembered choice > localhost defaults to "real", anything else (e.g. a
// Vercel deployment with no backend behind it) defaults to "mock".
(function () {
  var params = new URLSearchParams(location.search);
  var explicit = params.get("backend");

  if (explicit === "mock" || explicit === "real") {
    localStorage.setItem("lethe_backend", explicit);
  }

  var choice = explicit || localStorage.getItem("lethe_backend");

  if (choice !== "mock" && choice !== "real") {
    var isLocal = location.hostname === "localhost" || location.hostname === "127.0.0.1";
    choice = isLocal ? "real" : "mock";
  }

  window.LETHE_BACKEND_MODE = choice;
  document.write('<script src="' + (choice === "mock" ? "mock.js" : "app.js") + '"><\/script>');
})();
