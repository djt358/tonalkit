// In-app browsers (R84): WeChat, Weibo, QQ, Instagram, Facebook/Messenger and Line open links in
// their own webviews, which may not record or hand a file to the share sheet. The kit stops
// there, before consent, and tells the person to open the link in Safari.

const IN_APP_UA = /MicroMessenger|Weibo|QQ\/|Instagram|FBAN|FBAV|Line\//;

/** @param {string|undefined} userAgent */
export const isInAppBrowser = (userAgent) => IN_APP_UA.test(userAgent ?? "");
