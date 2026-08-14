"use strict";

browser.browserAction.onClicked.addListener(function () {
  browser.tabs.query({ active: true, currentWindow: true }).then(function (tabs) {
    if (!tabs.length || typeof tabs[0].url !== "string") {
      return null;
    }

    return browser.runtime.sendNativeMessage("yt_downloader", {
      url: tabs[0].url
    });
  }).then(function (response) {
    if (response && response.status === "error") {
      console.error(response.error);
    }
  }).catch(function (error) {
    console.error(error);
  });
});
