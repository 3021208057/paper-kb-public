(function () {
  window.MathJax = {
    loader: {
      load: ["[tex]/ams", "[tex]/boldsymbol", "[tex]/noerrors", "[tex]/noundefined"],
    },
    tex: {
      inlineMath: [
        ["$", "$"],
        ["\\(", "\\)"],
      ],
      displayMath: [
        ["$$", "$$"],
        ["\\[", "\\]"],
      ],
      processEscapes: true,
      processEnvironments: true,
      tags: "ams",
      packages: {
        "[+]": ["ams", "boldsymbol", "noerrors", "noundefined"],
      },
      macros: {
        bm: ["\\boldsymbol{#1}", 1],
      },
    },
    options: {
      skipHtmlTags: ["script", "noscript", "style", "textarea", "pre", "code"],
      ignoreHtmlClass: "tex2jax_ignore",
    },
    chtml: {
      scale: 0.98,
      mtextInheritFont: true,
    },
  };

  document.addEventListener("htmx:afterSettle", function (event) {
    if (window.MathJax && window.MathJax.typesetPromise) {
      window.MathJax.typesetPromise([event.target]).catch(function (error) {
        console.warn("MathJax typeset failed:", error);
      });
    }
  });
})();
