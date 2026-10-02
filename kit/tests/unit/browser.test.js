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

test("Safari and real browsers (including the standalone QQ Browser) go through", () => {
  for (const [name, ua] of Object.entries(BROWSERS)) assert.equal(isInAppBrowser(ua), false, name);
  assert.equal(isInAppBrowser(""), false);
  assert.equal(isInAppBrowser(undefined), false);
});
