"use strict";

const iconTimeouts = new Map();

function showStatusIcon(tabId, path) {
  const previousTimeout = iconTimeouts.get(tabId);
  if (previousTimeout) {
    clearTimeout(previousTimeout);
  }

  browser.browserAction.setIcon({ path: path, tabId: tabId });

  iconTimeouts.set(tabId, setTimeout(function () {
    browser.browserAction.setIcon({ path: null, tabId: tabId });
    iconTimeouts.delete(tabId);
  }, 3000));
}

browser.browserAction.onClicked.addListener(function (tab) {
  if (typeof tab.id !== "number" || typeof tab.url !== "string") {
    if (typeof tab.id === "number") {
      showStatusIcon(tab.id, "icons/save-this-media-red.svg");
    }
    console.error("The active tab does not have a downloadable URL.");
    return;
  }

  browser.runtime.sendNativeMessage("yt_downloader", {
    url: tab.url
  }).then(function (response) {
    if (response && response.status === "started") {
      showStatusIcon(tab.id, "icons/save-this-media-green.svg");
      return;
    }

    showStatusIcon(tab.id, "icons/save-this-media-red.svg");
    console.error(response && response.error ? response.error : "Unexpected native host response.");
  }).catch(function (error) {
    showStatusIcon(tab.id, "icons/save-this-media-red.svg");
    console.error(error);
  });
});
