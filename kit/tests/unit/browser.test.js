import { test } from "node:test";
import assert from "node:assert/strict";
import { isInAppBrowser } from "../../app/browser.js";

const IOS = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko)";

const IN_APP = {
  wechat: `${IOS} Mobile/15E148 MicroMessenger/8.0.49(0x18003137) NetType/WIFI Language/zh_CN`,
  weibo: `${IOS} Mobile/15E148 Weibo (iPhone15,2__weibo__14.5.0__iphone__os17.5)`,
  qq: `${IOS} Mobile/15E148 QQ/9.0.60.611 V1_IPH_SQ_9.0.60_1_APP_A Pixel/1179 Core/WKWebView`,
  instagram: `${IOS} Mobile/15E148 Instagram 330.0.3.12.92 (iPhone15,2; iOS 17_5; en_US; en; scale=3.00)`,
  facebook: `${IOS} Mobile/15E148 [FBAN/FBIOS;FBDV/iPhone15,2;FBMD/iPhone;FBSN/iOS;FBSV/17.5;FBAV/470.0.0.40.94]`,
  messenger: `${IOS} Mobile/15E148 [FBAN/MessengerForiOS;FBAV/460.0.0.36.109;FBBV/600000000]`,
  line: `${IOS} Mobile/15E148 Safari Line/14.10.0`,
};

const BROWSERS = {
  safari: `${IOS} Version/17.5 Mobile/15E148 Safari/604.1`,
  chrome_ios: `${IOS} CriOS/129.0.6668.69 Mobile/15E148 Safari/604.1`,
  firefox_ios: `${IOS} FxiOS/130.0 Mobile/15E148 Safari/605.1.15`,
  qq_browser: `${IOS} Mobile/15E148 MQQBrowser/14.9.0 Safari/604.1`,
  ipad_safari: "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
  headless: "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) HeadlessChrome/141.0.7390.37 Safari/537.36",
};

test("R84: WeChat, Weibo, QQ, Instagram, Facebook/Messenger and Line webviews are stopped", () => {
  for (const [name, ua] of Object.entries(IN_APP)) assert.equal(isInAppBrowser(ua), true, name);
});

// R92: each token on its own, so a regex edit can't quietly drop one.
const R92_TOKENS = {
  rednote: "xhsdiscover",
  douyin: "aweme",
  tiktok_old: "musical_ly",
  bytedance: "BytedanceWebview",
  tiktok: "TikTok",
  linkedin: "LinkedInApp",
  snapchat: "Snapchat",
};

test("R92: RedNote, Douyin, TikTok, LinkedIn and Snapchat are stopped, one test per token", () => {
  for (const [name, token] of Object.entries(R92_TOKENS)) {
    assert.equal(isInAppBrowser(`${IOS} Mobile/15E148 ${token}/1.0`), true, `${name}: ${token}`);
  }
});

test("R92: real user agents of those apps are stopped", () => {
  const apps = {
    rednote: `${IOS} Mobile/15E148 discover/8.45.1 (iPhone; iOS 17.5; Scale/3.00) Resolution/1170*2532 xhsdiscover NetType/WiFi`,
    douyin: `${IOS} Mobile/15E148 aweme_29.4.0 JsSdk/2.0 NetType/WIFI Channel/App Store ByteLocale/zh-Hans BytedanceWebview/d8a21c6`,
    tiktok: `${IOS} Mobile/15E148 musical_ly_35.1.0 JsSdk/2.0 NetType/WIFI Channel/App Store ByteLocale/en Region/US BytedanceWebview/d8a21c6`,
    tiktok_named: `${IOS} Mobile/15E148 TikTok 35.1.0 (iPhone15,2; iOS 17_5)`,
    linkedin: `${IOS} Mobile/15E148 [LinkedInApp]/9.30.1523`,
    snapchat: `${IOS} Mobile/15E148 Snapchat/12.89.0.38 (like Safari/8617.1.17.10.9, panda)`,
  };
  for (const [name, ua] of Object.entries(apps)) assert.equal(isInAppBrowser(ua), true, name);
});

test("plain iOS Safari and iOS Chrome (CriOS) still pass after R92", () => {
  assert.equal(isInAppBrowser(BROWSERS.safari), false);
  assert.equal(isInAppBrowser(BROWSERS.chrome_ios), false);
});

test("Safari and real browsers (including the standalone QQ Browser) go through", () => {
  for (const [name, ua] of Object.entries(BROWSERS)) assert.equal(isInAppBrowser(ua), false, name);
  assert.equal(isInAppBrowser(""), false);
  assert.equal(isInAppBrowser(undefined), false);
});
