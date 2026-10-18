var ASSET_VERSION = "1";
var TOTAL_STORY_PAGES = /* __TOTAL_STORY_PAGES__ */ 12;

var pages = /* __BOOK_PAGES_JSON__ */ [];

var pageCard = document.getElementById("pageCard");
var coverOverlay = document.getElementById("coverOverlay");
var coverTitle = document.getElementById("coverTitle");
var coverSubtitle = document.getElementById("coverSubtitle");
var coverStartBtn = document.getElementById("coverStartBtn");
var coverImage = document.getElementById("coverImage");

var flapStage = document.getElementById("flapStage");
var liftFlap = document.getElementById("liftFlap");
var realityImage = document.getElementById("realityImage");
var imaginaryImage = document.getElementById("imaginaryImage");
var imaginaryCaption = document.getElementById("imaginaryCaption");
var realityBadge = document.getElementById("realityBadge");
var imaginaryBadge = document.getElementById("imaginaryBadge");
var flapPullTab = document.getElementById("flapPullTab");
var flapHingeStitch = document.querySelector(".flap-hinge-stitch");

var pageCopy = document.getElementById("pageCopy");
var pageLabel = document.getElementById("pageLabel");
var pageProgress = document.getElementById("pageProgress");
var pageTitle = document.getElementById("pageTitle");
var pageText = document.getElementById("pageText");

var flapControlCard = document.getElementById("flapControlCard");
var flapStateIndicator = document.getElementById("flapStateIndicator");
var flapHintCopy = document.getElementById("flapHintCopy");
var flapActionBtn = document.getElementById("flapActionBtn");
var flapBtnIcon = document.getElementById("flapBtnIcon");
var flapBtnText = document.getElementById("flapBtnText");

var prevBtn = document.getElementById("prevBtn");
var nextBtn = document.getElementById("nextBtn");
var storyPrevBtn = document.getElementById("storyPrevBtn");
var storyNextBtn = document.getElementById("storyNextBtn");
var pageDots = document.getElementById("pageDots");
var focusTextBtn = document.getElementById("focusTextBtn");

var endPageArt = document.getElementById("endPageArt");
var endPageKicker = document.getElementById("endPageKicker");
var endPageTitle = document.getElementById("endPageTitle");
var endPageSubtitle = document.getElementById("endPageSubtitle");
var replayBtn = document.getElementById("replayBtn");
var celebrationLayer = document.getElementById("celebrationLayer");

var portraitBanner = document.getElementById("portraitBanner");
var dismissPortraitBanner = document.getElementById("dismissPortraitBanner");

var currentIndex = 0;
var isFlapOpen = false;
var flapProgress = 0;
var isFocusTextMode = false;
var confettiTimer = null;

function assetUrl(path) {
  if (!path) {
    return "";
  }
  if (path.indexOf("data:") === 0 || path.indexOf("http://") === 0 || path.indexOf("https://") === 0) {
    return path;
  }
  return path + "?v=" + ASSET_VERSION;
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function formatStoryLine(line, refrain) {
  var escaped = escapeHtml(line);
  if (refrain) {
    var escapedRefrain = escapeHtml(refrain);
    escaped = escaped.split(escapedRefrain).join('<span class="story-refrain">' + escapedRefrain + "</span>");
  }
  return escaped;
}

function getWrappedIndex(index) {
  if (index < 0) {
    return pages.length - 1;
  }
  if (index >= pages.length) {
    return 0;
  }
  return index;
}

function preloadNeighbors(index) {
  var neighborIndexes = [getWrappedIndex(index - 1), getWrappedIndex(index + 1)];
  var i;
  for (i = 0; i < neighborIndexes.length; i += 1) {
    var neighbor = pages[neighborIndexes[i]];
    if (!neighbor) {
      continue;
    }
    if (neighbor.coverImage) {
      var cImg = new Image();
      cImg.src = assetUrl(neighbor.coverImage);
    }
    if (neighbor.realImage) {
      var rImg = new Image();
      rImg.src = assetUrl(neighbor.realImage);
    }
    if (neighbor.imaginaryImage) {
      var iImg = new Image();
      iImg.src = assetUrl(neighbor.imaginaryImage);
    }
  }
}

function applyFlapProgress(progress, isDragging) {
  var clamped = Math.max(0, Math.min(1, progress));
  flapProgress = clamped;
  isFlapOpen = clamped >= 0.5;

  flapStage.style.setProperty("--flap-progress", clamped.toFixed(3));
  flapStage.classList.toggle("is-dragging", Boolean(isDragging));
  flapStage.classList.toggle("is-lifted", isFlapOpen);
  liftFlap.setAttribute("aria-expanded", isFlapOpen ? "true" : "false");

  flapControlCard.classList.toggle("is-imaginary-active", isFlapOpen);
  if (isFlapOpen) {
    flapStateIndicator.textContent = "✨ Showing: Imaginary World!";
    flapBtnIcon.textContent = "🔽";
    flapBtnText.textContent = "Lower Flap (Back to Real World)";
  } else {
    flapStateIndicator.textContent = "🏡 Showing: Real World";
    flapBtnIcon.textContent = "🔼";
    flapBtnText.textContent = "Lift Up Flap";
  }
}

function toggleFlap(forceState) {
  var page = pages[currentIndex];
  if (!page || !page.hasFlap) {
    return;
  }
  var nextState = typeof forceState === "boolean" ? forceState : !isFlapOpen;
  applyFlapProgress(nextState ? 1 : 0, false);
}

function setupFlapGestures() {
  var startY = null;
  var startX = null;
  var startProgress = 0;
  var moved = false;
  var stageHeight = 320;

  function onPointerDown(e) {
    var page = pages[currentIndex];
    if (!page || !page.hasFlap) {
      return;
    }
    if (e.pointerType === "mouse" && e.button !== 0) {
      return;
    }
    startY = e.clientY;
    startX = e.clientX;
    startProgress = flapProgress;
    moved = false;
    stageHeight = Math.max(180, flapStage.clientHeight * 0.65);
    if (liftFlap.setPointerCapture && e.pointerId !== undefined) {
      try {
        liftFlap.setPointerCapture(e.pointerId);
      } catch (err) {
        /* ignore */
      }
    }
  }

  function onPointerMove(e) {
    if (startY === null) {
      return;
    }
    var dy = startY - e.clientY;
    var dx = Math.abs(e.clientX - startX);

    if (!moved && Math.abs(dy) < 8 && dx < 8) {
      return;
    }

    if (Math.abs(dy) > dx * 0.75 || moved) {
      moved = true;
      var deltaProgress = dy / stageHeight;
      applyFlapProgress(startProgress + deltaProgress, true);
    }
  }

  function onPointerUp(e) {
    if (startY === null) {
      return;
    }
    var dy = startY - e.clientY;
    var dx = e.clientX - startX;
    startY = null;
    startX = null;

    if (!moved && Math.abs(dx) > 48 && Math.abs(dx) > Math.abs(dy) * 1.4) {
      if (dx < 0) {
        changePage(currentIndex + 1, "next");
      } else {
        changePage(currentIndex - 1, "prev");
      }
      return;
    }

    if (!moved || Math.abs(dy) < 10) {
      toggleFlap();
      return;
    }

    if (dy > 28) {
      applyFlapProgress(1, false);
    } else if (dy < -28) {
      applyFlapProgress(0, false);
    } else {
      applyFlapProgress(flapProgress >= 0.5 ? 1 : 0, false);
    }
  }

  liftFlap.addEventListener("pointerdown", onPointerDown);
  liftFlap.addEventListener("pointermove", onPointerMove);
  liftFlap.addEventListener("pointerup", onPointerUp);
  liftFlap.addEventListener("pointercancel", function () {
    startY = null;
    applyFlapProgress(isFlapOpen ? 1 : 0, false);
  });

  var cardStartX = null;
  var cardStartY = null;
  pageCard.addEventListener("pointerdown", function (e) {
    if (e.target.closest("#liftFlap") || e.target.closest("button")) {
      return;
    }
    cardStartX = e.clientX;
    cardStartY = e.clientY;
  });
  pageCard.addEventListener("pointerup", function (e) {
    if (cardStartX === null) {
      return;
    }
    var dx = e.clientX - cardStartX;
    var dy = e.clientY - cardStartY;
    cardStartX = null;
    cardStartY = null;

    if (Math.abs(dx) > 48 && Math.abs(dx) > Math.abs(dy) * 1.3) {
      if (dx < 0) {
        changePage(currentIndex + 1, "next");
      } else {
        changePage(currentIndex - 1, "prev");
      }
      return;
    }
    if (isFlapOpen && dy > 36 && Math.abs(dy) > Math.abs(dx)) {
      toggleFlap(false);
      return;
    }
    if (isFlapOpen && e.target.closest(".imaginary-scene")) {
      toggleFlap(false);
    }
  });
}

function clearCelebration() {
  if (confettiTimer) {
    clearTimeout(confettiTimer);
    confettiTimer = null;
  }
  celebrationLayer.innerHTML = "";
  endPageArt.classList.remove("is-animating");
}

function createConfettiPiece(className, left, styleMap) {
  var piece = document.createElement("span");
  var key;
  piece.className = className;
  piece.style.left = left;
  for (key in styleMap) {
    if (Object.prototype.hasOwnProperty.call(styleMap, key)) {
      piece.style.setProperty(key, styleMap[key]);
    }
  }
  celebrationLayer.appendChild(piece);
}

function launchCelebration() {
  var colors = ["#f6b924", "#1e5aa8", "#6ca82c", "#ea580c", "#38bdf8", "#fbbf24", "#ffffff"];
  var i;
  clearCelebration();

  for (i = 0; i < 40; i += 1) {
    var color = colors[i % colors.length];
    var left = 2 + ((i * 53) % 96);
    var duration = 2600 + (i % 8) * 220;
    var drift = -140 + ((i * 29) % 280);
    var delay = (i % 10) * 90;
    var spin = 540 + ((i % 6) * 180);

    createConfettiPiece("confetti-piece" + (i % 4 === 0 ? " is-ribbon" : ""), left + "%", {
      "background": color,
      "color": color,
      "--duration": duration + "ms",
      "--drift-x": drift + "px",
      "--spin": spin + "deg",
      "animation-delay": delay + "ms"
    });
  }

  for (i = 0; i < 26; i += 1) {
    var bColor = colors[(i + 2) % colors.length];
    var bLeft = 16 + ((i * 11) % 68);
    var burstX = -220 + ((i * 31) % 440);
    var burstY = -240 + ((i * 43) % 260);

    createConfettiPiece("confetti-piece is-burst", bLeft + "%", {
      "background": bColor,
      "color": bColor,
      "--burst-x": burstX + "px",
      "--burst-y": burstY + "px",
      "animation-delay": (i % 7) * 70 + "ms"
    });
  }

  confettiTimer = setTimeout(clearCelebration, 5200);
}

function buildPageDots() {
  var i;
  pageDots.innerHTML = "";
  for (i = 1; i <= TOTAL_STORY_PAGES; i += 1) {
    (function (pageIdx) {
      var dot = document.createElement("button");
      dot.type = "button";
      dot.className = "page-dot";
      dot.setAttribute("aria-label", "Go to Page " + pageIdx);
      dot.addEventListener("click", function () {
        changePage(pageIdx, pageIdx > currentIndex ? "next" : "prev");
      });
      pageDots.appendChild(dot);
    })(i);
  }
}

function updatePageDots() {
  var dots = pageDots.querySelectorAll(".page-dot");
  var i;
  for (i = 0; i < dots.length; i += 1) {
    dots[i].classList.toggle("is-active", i + 1 === currentIndex);
  }
}

function renderPage(index, direction) {
  var page = pages[index];
  if (!page) {
    return;
  }

  currentIndex = index;
  var isCover = index === 0;
  var isEnd = page.kind === "the-end";

  applyFlapProgress(0, false);

  pageCard.classList.toggle("is-cover", isCover);
  pageCard.classList.toggle("is-end", isEnd);
  pageCard.classList.toggle("is-focus-text", isFocusTextMode && !isCover && !isEnd);

  coverOverlay.hidden = !isCover;
  coverImage.hidden = !isCover;
  flapStage.hidden = isCover || isEnd;
  endPageArt.hidden = !isEnd;
  endPageArt.classList.toggle("is-visible", isEnd);

  pageCopy.hidden = isCover || isEnd;
  pageCopy.setAttribute("aria-hidden", isCover || isEnd ? "true" : "false");

  // Show/hide flap UI depending on whether this page has a lift-flap
  flapControlCard.hidden = !page.hasFlap;
  if (flapPullTab) {
    flapPullTab.hidden = !page.hasFlap;
  }
  if (realityBadge) {
    realityBadge.hidden = !page.hasFlap;
  }
  if (imaginaryBadge) {
    imaginaryBadge.hidden = !page.hasFlap;
  }
  if (flapHingeStitch) {
    flapHingeStitch.hidden = !page.hasFlap;
  }

  if (isCover) {
    coverTitle.textContent = page.title;
    coverSubtitle.textContent = page.subtitle || "";
    coverImage.src = assetUrl(page.coverImage);
  } else if (!isEnd) {
    realityImage.src = assetUrl(page.realImage);
    realityImage.alt = page.label + ": " + page.title;
    imaginaryImage.src = assetUrl(page.imaginaryImage || page.realImage);
    imaginaryImage.alt = page.label + " (Imaginary scene): " + page.title;
    imaginaryCaption.textContent = page.imaginaryCaption || "✨ Imaginary World";
    flapHintCopy.textContent = page.flapHint || "Lift the flap to see the imaginary scene!";
  } else {
    endPageKicker.textContent = page.kicker || "HOORAY!";
    endPageTitle.textContent = page.title;
    endPageSubtitle.textContent = page.text[0] || "";
  }

  pageLabel.textContent = page.label;
  pageTitle.textContent = page.title;
  pageProgress.textContent = index + " / " + TOTAL_STORY_PAGES;

  var lines = [];
  var i;
  for (i = 0; i < page.text.length; i += 1) {
    lines.push("<p>" + formatStoryLine(page.text[i], page.refrain) + "</p>");
  }
  pageText.innerHTML = lines.join("");

  updatePageDots();

  pageCard.classList.remove("turn-forward", "turn-backward");
  void pageCard.offsetWidth;
  pageCard.classList.add(direction === "prev" ? "turn-backward" : "turn-forward");

  clearCelebration();
  if (isEnd) {
    void endPageArt.offsetWidth;
    endPageArt.classList.add("is-animating");
    launchCelebration();
  }

  preloadNeighbors(index);
}

function changePage(nextIndex, direction) {
  var wrapped = getWrappedIndex(nextIndex);
  if (wrapped === currentIndex) {
    return;
  }
  renderPage(wrapped, direction);
}

prevBtn.addEventListener("click", function () {
  changePage(currentIndex - 1, "prev");
});

nextBtn.addEventListener("click", function () {
  changePage(currentIndex + 1, "next");
});

storyPrevBtn.addEventListener("click", function () {
  changePage(currentIndex - 1, "prev");
});

storyNextBtn.addEventListener("click", function () {
  changePage(currentIndex + 1, "next");
});

coverStartBtn.addEventListener("click", function () {
  changePage(1, "next");
});

replayBtn.addEventListener("click", function () {
  changePage(0, "prev");
});

flapActionBtn.addEventListener("click", function () {
  toggleFlap();
});

focusTextBtn.addEventListener("click", function () {
  isFocusTextMode = !isFocusTextMode;
  focusTextBtn.setAttribute("aria-pressed", isFocusTextMode ? "true" : "false");
  focusTextBtn.textContent = isFocusTextMode ? "🎨 Show Artwork" : "Aa Text Only";
  pageCard.classList.toggle("is-focus-text", isFocusTextMode && currentIndex > 0 && currentIndex < pages.length - 1);
});

if (dismissPortraitBanner) {
  dismissPortraitBanner.addEventListener("click", function () {
    portraitBanner.classList.add("is-dismissed");
  });
}

document.addEventListener("keydown", function (event) {
  if (event.key === "ArrowRight") {
    event.preventDefault();
    changePage(currentIndex + 1, "next");
  } else if (event.key === "ArrowLeft") {
    event.preventDefault();
    changePage(currentIndex - 1, "prev");
  } else if (event.key === "ArrowUp" || event.key === " " || event.key === "f" || event.key === "F") {
    if (pages[currentIndex] && pages[currentIndex].hasFlap) {
      event.preventDefault();
      if (event.key === "ArrowUp") {
        toggleFlap(true);
      } else {
        toggleFlap();
      }
    }
  } else if (event.key === "ArrowDown") {
    if (pages[currentIndex] && pages[currentIndex].hasFlap) {
      event.preventDefault();
      toggleFlap(false);
    }
  }
});

buildPageDots();
setupFlapGestures();
renderPage(0, "next");
