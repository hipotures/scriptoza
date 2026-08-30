"use strict";

const badgeTimeouts = new Map();

function showBadge(tabId, text, color) {
  const previousTimeout = badgeTimeouts.get(tabId);
  if (previousTimeout) {
    clearTimeout(previousTimeout);
  }

  browser.browserAction.setBadgeBackgroundColor({ color: color, tabId: tabId });
  browser.browserAction.setBadgeText({ text: text, tabId: tabId });

  badgeTimeouts.set(tabId, setTimeout(function () {
    browser.browserAction.setBadgeText({ text: "", tabId: tabId });
    badgeTimeouts.delete(tabId);
  }, 3000));
}

browser.browserAction.onClicked.addListener(function (tab) {
  if (typeof tab.id !== "number" || typeof tab.url !== "string") {
    if (typeof tab.id === "number") {
      showBadge(tab.id, "!", "#dc2626");
    }
    console.error("The active tab does not have a downloadable URL.");
    return;
  }

  showBadge(tab.id, "…", "#2563eb");

  browser.runtime.sendNativeMessage("yt_downloader", {
    url: tab.url
  }).then(function (response) {
    if (response && response.status === "started") {
      showBadge(tab.id, "OK", "#16a34a");
      return;
    }

    showBadge(tab.id, "!", "#dc2626");
    console.error(response && response.error ? response.error : "Unexpected native host response.");
  }).catch(function (error) {
    showBadge(tab.id, "!", "#dc2626");
    console.error(error);
  });
});
