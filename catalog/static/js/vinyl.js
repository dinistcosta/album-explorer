(function () {
  var wrap = document.querySelector(".sleeve-wrap");
  if (!wrap) return;
  var reduced = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (reduced) {
    wrap.classList.add("out", "no-motion");
    return;
  }
  requestAnimationFrame(function () {
    requestAnimationFrame(function () { wrap.classList.add("out"); });
  });
})();
