/* Mission control stays current without a manual refresh.
   /live is a cheap rev of loans + items. When it changes, we swap the board. */
(function () {
  const INTERVAL_MS = 3000;
  const VENDOR_MS = 20000;
  const path = location.pathname;
  const watch = path === "/" || path.startsWith("/loans/");

  const chip = document.getElementById("live-chip");
  const label = chip && chip.querySelector("[data-live-label]");
  let rev = null;
  let vendorTick = Math.floor(Date.now() / VENDOR_MS);

  function setChip(kind, text) {
    if (!chip || !label) return;
    chip.className = "status-chip " + kind;
    chip.title = text;
    label.textContent = text;
  }

  function adopt(html) {
    const doc = new DOMParser().parseFromString(html, "text/html");
    const nextMain = doc.querySelector("main.wrap");
    const main = document.querySelector("main.wrap");
    if (nextMain && main) main.replaceWith(nextMain);
    const nextChips = doc.querySelectorAll("header.topbar .status-chip[data-sync]");
    const chips = document.querySelectorAll("header.topbar .status-chip[data-sync]");
    nextChips.forEach(function (el, i) {
      if (chips[i]) chips[i].replaceWith(el.cloneNode(true));
    });
  }

  async function tick() {
    if (document.visibilityState === "hidden") return;
    try {
      const live = await fetch("/live", { cache: "no-store" });
      if (!live.ok) throw new Error("live " + live.status);
      const data = await live.json();
      const nextVendor = Math.floor(Date.now() / VENDOR_MS);
      const changed = rev !== null && data.rev !== rev;
      const vendorsDue = nextVendor !== vendorTick;
      setChip("pass", "live");
      if (watch && (changed || vendorsDue)) {
        const page = await fetch(path + location.search, { cache: "no-store" });
        if (page.ok) adopt(await page.text());
      }
      rev = data.rev;
      vendorTick = nextVendor;
    } catch (err) {
      setChip("fail", "offline");
    }
  }

  setInterval(tick, INTERVAL_MS);
  tick();
  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "visible") tick();
  });
})();
