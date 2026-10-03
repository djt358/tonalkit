// In-app browsers (R84, R92): WeChat, Weibo, QQ, Instagram, Facebook/Messenger, Line, RedNote,
// Douyin/TikTok, LinkedIn and Snapchat open links in their own webviews, which may not record or
// hand a file to the share sheet. The kit stops there, before consent, and tells the person to
// open the link in Safari.

// R84: WeChat, Weibo, QQ, Instagram, Facebook/Messenger, Line. R92: RedNote (xhsdiscover), Douyin and
// TikTok (aweme, musical_ly, BytedanceWebview, TikTok), LinkedIn, Snapchat.
const IN_APP_UA =
  /MicroMessenger|Weibo|QQ\/|Instagram|FBAN|FBAV|Line\/|xhsdiscover|aweme|musical_ly|BytedanceWebview|TikTok|LinkedInApp|Snapchat/;

/** @param {string|undefined} userAgent */
export const isInAppBrowser = (userAgent) => IN_APP_UA.test(userAgent ?? "");
