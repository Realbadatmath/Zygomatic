const API_PLATFORM_IDS = new Set(["youtube", "x", "telegram", "vk"]);

// ── Dashboard API base ────────────────────────────────────────────────────────
// The static site is served by its own http.server (:8090); the Flask blueprints
// it talks to live on the dashboard (:5000). No host is hardcoded: the dashboard
// is assumed to run on whatever host served this page. Override by setting
// window.ZYG_API_BASE (e.g. in a <script> before app.js) when they differ.
const API_BASE = (() => {
  if (typeof window !== "undefined" && window.ZYG_API_BASE) {
    return String(window.ZYG_API_BASE).replace(/\/+$/, "");
  }
  const { protocol, hostname, port } = location;
  // Already served by the dashboard itself → same-origin, relative URLs.
  if (port === "5000") return "";
  return `${protocol}//${hostname}:5000`;
})();

const STORAGE_KEY   = "creator_nexus_channels_v2";
const ADSENSE_KEY   = "creator_nexus_adsense_v1";

// ── Region → platform configs ─────────────────────────────────────────────────
const REGION_PLATFORMS = {
  english:  [
    { id: "youtube",   title: "YouTube",   color: "FF0000", slug: "youtube" },
    { id: "kick",      title: "Kick",      color: "53FC18", slug: "kick" },
    { id: "tiktok",    title: "TikTok",    color: "FE2C55", slug: "tiktok" },
    { id: "instagram", title: "Instagram", color: "E4405F", slug: "instagram" },
    { id: "facebook",  title: "Facebook",  color: "1877F2", slug: "facebook" },
    { id: "x",         title: "X",         color: "ffffff", slug: "x" },
  ],
  spanish: [
    { id: "youtube",   title: "YouTube",   color: "FF0000", slug: "youtube" },
    { id: "instagram", title: "Instagram", color: "E4405F", slug: "instagram" },
    { id: "facebook",  title: "Facebook",  color: "1877F2", slug: "facebook" },
    { id: "tiktok",    title: "TikTok",    color: "FE2C55", slug: "tiktok" },
    { id: "x",         title: "X",         color: "ffffff", slug: "x" },
  ],
  french: [
    { id: "youtube",   title: "YouTube",   color: "FF0000", slug: "youtube" },
    { id: "instagram", title: "Instagram", color: "E4405F", slug: "instagram" },
    { id: "facebook",  title: "Facebook",  color: "1877F2", slug: "facebook" },
    { id: "tiktok",    title: "TikTok",    color: "FE2C55", slug: "tiktok" },
    { id: "x",         title: "X",         color: "ffffff", slug: "x" },
  ],
  indian: [
    { id: "youtube",   title: "YouTube",   color: "FF0000", slug: "youtube" },
    { id: "instagram", title: "Instagram", color: "E4405F", slug: "instagram" },
    { id: "facebook",  title: "Facebook",  color: "1877F2", slug: "facebook" },
    { id: "x",         title: "X",         color: "ffffff", slug: "x" },
    { id: "whatsapp",  title: "WhatsApp",  color: "25D366", slug: "whatsapp" },
  ],
  chinese: [
    { id: "bilibili",   title: "Bilibili",  color: "00A1D6", slug: "bilibili" },
    { id: "sinaweibo",  title: "Weibo",     color: "E9191F", slug: "sinaweibo" },
    { id: "wechat",     title: "WeChat",    color: "07C160", slug: "wechat" },
    { id: "qq",         title: "QQ",        color: "12B7F5", slug: "qq" },
    { id: "douyin",     title: "Douyin",    color: "FE2C55", slug: "tiktok" },
    { id: "zhihu",      title: "Zhihu",     color: "0084FF", slug: "zhihu" },
    { id: "youku",      title: "Youku",     color: "3DBEFF", slug: "youku" },
    { id: "iqiyi",      title: "iQIYI",     color: "00BE06", slug: "iqiyi" },
  ],
  russian: [
    { id: "vk",            title: "VK",       color: "0077FF", slug: "vk" },
    { id: "telegram",      title: "Telegram", color: "26A5E4", slug: "telegram" },
    { id: "odnoklassniki", title: "OK.ru",    color: "EE8208", slug: "odnoklassniki" },
    { id: "yandex",        title: "Yandex",   color: "FC3F1D", slug: "yandex" },
    { id: "youtube",       title: "YouTube",  color: "FF0000", slug: "youtube" },
    { id: "tiktok",        title: "TikTok",   color: "FE2C55", slug: "tiktok" },
    { id: "instagram",     title: "Instagram",color: "E4405F", slug: "instagram" },
    { id: "rutube",        title: "Rutube",   color: "A6001B", slug: "rutube" },
  ],
};

// ── Platforms for text-post promotion ────────────────────────────────────────
const POST_PLATFORMS = [
  { id: "facebook",  title: "Facebook",        color: "1877F2", slug: "facebook"  },
  { id: "instagram", title: "Instagram",        color: "E4405F", slug: "instagram" },
  { id: "x",         title: "X / Twitter",      color: "ffffff", slug: "x"         },
  { id: "linkedin",  title: "LinkedIn",         color: "0A66C2", slug: "linkedin"  },
  { id: "reddit",    title: "Reddit",           color: "FF4500", slug: "reddit"    },
  { id: "pinterest", title: "Pinterest",        color: "E60023", slug: "pinterest" },
  { id: "threads",   title: "Threads",          color: "ffffff", slug: "threads"   },
  { id: "quora",     title: "Quora",            color: "B92B27", slug: "quora"     },
  { id: "medium",    title: "Medium",           color: "ffffff", slug: "medium"    },
  { id: "google",    title: "Google Business",  color: "4285F4", slug: "google"    },
  { id: "tumblr",    title: "Tumblr",           color: "35465C", slug: "tumblr"    },
  { id: "discord",   title: "Discord",          color: "5865F2", slug: "discord"   },
];

const POST_COLS = [
  { id: "idea",   label: "Ideas"  },
  { id: "draft",  label: "Draft"  },
  { id: "ready",  label: "Ready"  },
  { id: "posted", label: "Posted" },
];

// ── General policy rules (platform-wide, applied to every channel/subchannel) ─
const GENERAL_POLICY_RULES = [
  "All content is long-form only — no YouTube Shorts, Reels, or sub-60-second clip formats are produced on any channel.",
  "Long-form ad revenue split: 55% creator / 45% YouTube — size content investment against this effective rate.",
  "Every video must be a minimum of 8 minutes to qualify for mid-roll ad placement; target 10–20 minutes for optimal ad density.",
  "AI-generated or AI-altered content (narration, visuals, B-roll, scripts, graphics) must be disclosed using YouTube Studio's 'Altered or Synthetic Content' toggle before publishing (YouTube AI Disclosure Policy, May 2025).",
  "Thumbnails and titles must accurately represent video content — misleading clickbait triggers Misleading Metadata Policy enforcement and demonetisation review.",
  "Excessive profanity in titles, thumbnails, or within the first 30 seconds restricts ad inventory; keep the opening ad-safe to preserve full monetisation.",
  "All sponsored content, affiliate relationships, and gifted or loaned products must be disclosed verbally in-video and in the description (FTC Endorsement Guides — civil penalties up to $51,744 per violation).",
  "All third-party music, footage, and images must be licensed or qualify as transformative fair use with substantial commentary; an uncontested copyright claim diverts 100% of ad revenue to the rights holder.",
  "Repetitive, templated, or auto-generated content without meaningful original commentary is demonetised under the July 2025 Inauthentic Content Policy.",
  "Coverage of sensitive events (mass casualties, disasters, political crises, active conflict) requires clear educational or journalistic framing; exploitation without context is grounds for demonetisation.",
  "No hate speech, harassment, dangerous activities, or content that endangers minors — a single Community Guidelines strike can suspend monetisation across all channels.",
  "Do not mark content as 'Made for Kids' unless it is genuinely directed at children — this disables all ad targeting and eliminates the majority of revenue.",
];

// ── Dialog configs ────────────────────────────────────────────────────────────
const ACCOUNT_DIALOGS = {
  primaryContact: {
    title: "Primary Contact",
    fields: [
      { id: "name",     label: "Full Name",     type: "text",     ph: "John Doe" },
      { id: "role",     label: "Role / Title",  type: "text",     ph: "Channel Manager" },
      { id: "email",    label: "Email",         type: "email",    ph: "contact@email.com" },
      { id: "phone",    label: "Phone Number",  type: "text",     ph: "+1 555 000 0000" },
      { id: "telegram", label: "Telegram",      type: "text",     ph: "@username" },
      { id: "whatsapp", label: "WhatsApp",      type: "text",     ph: "+1 555 000 0000" },
      { id: "notes",    label: "Notes",         type: "textarea", ph: "Working hours, timezone, notes…" },
    ],
  },
  youtube: {
    title: "YouTube Account",
    fields: [
      { id: "channelUrl",    label: "Channel URL",       type: "text",     ph: "https://youtube.com/@yourhandle" },
      { id: "username",      label: "Username / Handle", type: "text",     ph: "@YourChannel" },
      { id: "email",         label: "Email",             type: "email",    ph: "account@example.com" },
      { id: "password",      label: "Password",          type: "password", ph: "••••••••" },
      { id: "recoveryEmail", label: "Recovery Email",    type: "email",    ph: "recovery@email.com" },
      { id: "phone",         label: "Phone (2FA)",       type: "text",     ph: "+1 555 000 0000" },
      { id: "apiKey",        label: "Data API Key",      type: "text",     ph: "AIza..." },
      { id: "apiKeyLimit",   label: "API Key Limit",     type: "text",     ph: "e.g. 10,000 units/day" },
      { id: "clientId",      label: "OAuth Client ID",   type: "text",     ph: "123456789-abc..." },
      { id: "clientSecret",  label: "OAuth Client Secret", type: "text",  ph: "GOCSPX-..." },
      { id: "notes",         label: "Notes",             type: "textarea", ph: "Recovery codes, extra info…" },
    ],
  },
  facebook: {
    title: "Facebook Account",
    fields: [
      { id: "profileUrl",   label: "Profile / Page URL", type: "text",     ph: "https://facebook.com/yourpage" },
      { id: "email",        label: "Email",               type: "email",    ph: "account@email.com" },
      { id: "password",     label: "Password",            type: "password", ph: "••••••••" },
      { id: "phone",        label: "Phone (2FA)",         type: "text",     ph: "+1 555 000 0000" },
      { id: "appId",        label: "App ID",              type: "text",     ph: "1234567890" },
      { id: "appSecret",    label: "App Secret",          type: "text",     ph: "abc123..." },
      { id: "accessToken",  label: "Page Access Token",   type: "text",     ph: "EAABwzLix..." },
      { id: "notes",        label: "Notes",               type: "textarea", ph: "Extra info…" },
    ],
  },
  google: {
    title: "Google Account",
    fields: [
      { id: "email",        label: "Email",          type: "email",    ph: "yourname@example.com" },
      { id: "password",     label: "Password",       type: "password", ph: "••••••••" },
      { id: "recoveryEmail",label: "Recovery Email", type: "email",    ph: "backup@email.com" },
      { id: "phone",        label: "Phone (2FA)",    type: "text",     ph: "+1 555 000 0000" },
      { id: "clientId",     label: "OAuth Client ID", type: "text",   ph: "123456789-abc..." },
      { id: "clientSecret", label: "OAuth Client Secret", type: "text", ph: "GOCSPX-..." },
      { id: "notes",        label: "Notes",          type: "textarea", ph: "Extra info…" },
    ],
  },
  phone: {
    title: "Phone Number",
    fields: [
      { id: "number",    label: "Phone Number",   type: "text",     ph: "+1 555 000 0000" },
      { id: "simSlot",   label: "Sim Card Slot",  type: "text",     ph: "e.g. Slot 1 / Slot 2" },
      { id: "carrier",   label: "Carrier",        type: "text",     ph: "T-Mobile, Verizon…" },
      { id: "sim",       label: "SIM / Account #", type: "text",    ph: "Account or SIM serial" },
      { id: "pin",       label: "PIN / Password", type: "password", ph: "••••" },
      { id: "notes",     label: "Notes",          type: "textarea", ph: "Linked accounts, notes…" },
    ],
  },
  googleCloud: {
    title: "Google Cloud Account",
    fields: [
      { id: "projectId",    label: "Project ID",      type: "text",     ph: "my-project-123" },
      { id: "projectName",  label: "Project Name",    type: "text",     ph: "Creator Nexus Prod" },
      { id: "email",        label: "Service Account", type: "email",    ph: "service@project.iam.gserviceaccount.com" },
      { id: "apiKey",       label: "API Key",         type: "text",     ph: "AIza..." },
      { id: "privateKeyId", label: "Private Key ID",  type: "text",     ph: "abc123…" },
      { id: "notes",        label: "Notes",           type: "textarea", ph: "Billing alerts, quota notes…" },
    ],
  },
  email: {
    title: "Email Address",
    fields: [
      { id: "address",      label: "Email Address",  type: "email",    ph: "you@domain.com" },
      { id: "provider",     label: "Provider",       type: "text",     ph: "Gmail, ProtonMail, Outlook…" },
      { id: "password",     label: "Password",       type: "password", ph: "••••••••" },
      { id: "recoveryEmail",label: "Recovery Email", type: "email",    ph: "backup@email.com" },
      { id: "imap",         label: "IMAP Server",    type: "text",     ph: "imap.gmail.com:993" },
      { id: "smtp",         label: "SMTP Server",    type: "text",     ph: "smtp.gmail.com:465" },
      { id: "notes",        label: "Notes",          type: "textarea", ph: "App passwords, notes…" },
    ],
  },
  x: {
    title: "X Account",
    fields: [
      { id: "profileUrl",         label: "Profile URL",         type: "text",     ph: "https://x.com/yourhandle" },
      { id: "username",           label: "Username / Handle",   type: "text",     ph: "@YourHandle" },
      { id: "email",              label: "Email",               type: "email",    ph: "account@email.com" },
      { id: "password",           label: "Password",            type: "password", ph: "••••••••" },
      { id: "phone",              label: "Phone (2FA)",         type: "text",     ph: "+1 555 000 0000" },
      { id: "apiKey",             label: "API Key",             type: "text",     ph: "xAI..." },
      { id: "apiSecret",          label: "API Key Secret",      type: "text",     ph: "abc123..." },
      { id: "accessToken",        label: "Access Token",        type: "text",     ph: "123456789-abc..." },
      { id: "accessTokenSecret",  label: "Access Token Secret", type: "text",     ph: "xyz..." },
      { id: "bearerToken",        label: "Bearer Token",        type: "text",     ph: "AAAA..." },
      { id: "notes",              label: "Notes",               type: "textarea", ph: "Extra info…" },
    ],
  },
  kick: {
    title: "Kick Account",
    fields: [
      { id: "channelUrl", label: "Channel URL",       type: "text",     ph: "https://kick.com/yourchannel" },
      { id: "username",   label: "Username",           type: "text",     ph: "YourChannel" },
      { id: "email",      label: "Email",              type: "email",    ph: "account@email.com" },
      { id: "password",   label: "Password",           type: "password", ph: "••••••••" },
      { id: "phone",      label: "Phone (2FA)",        type: "text",     ph: "+1 555 000 0000" },
      { id: "notes",      label: "Notes",              type: "textarea", ph: "Extra info…" },
    ],
  },
  tiktok: {
    title: "TikTok Account",
    fields: [
      { id: "profileUrl", label: "Profile URL",        type: "text",     ph: "https://tiktok.com/@yourhandle" },
      { id: "username",   label: "Username / Handle",  type: "text",     ph: "@YourHandle" },
      { id: "email",      label: "Email",              type: "email",    ph: "account@email.com" },
      { id: "password",   label: "Password",           type: "password", ph: "••••••••" },
      { id: "phone",      label: "Phone (2FA)",        type: "text",     ph: "+1 555 000 0000" },
      { id: "appId",      label: "App ID",             type: "text",     ph: "12345" },
      { id: "appSecret",  label: "App Secret",         type: "text",     ph: "abc123..." },
      { id: "notes",      label: "Notes",              type: "textarea", ph: "Extra info…" },
    ],
  },
  instagram: {
    title: "Instagram Account",
    fields: [
      { id: "profileUrl",  label: "Profile URL",         type: "text",     ph: "https://instagram.com/yourhandle" },
      { id: "username",    label: "Username",             type: "text",     ph: "@YourHandle" },
      { id: "email",       label: "Email",               type: "email",    ph: "account@email.com" },
      { id: "password",    label: "Password",            type: "password", ph: "••••••••" },
      { id: "phone",       label: "Phone (2FA)",         type: "text",     ph: "+1 555 000 0000" },
      { id: "appId",       label: "App ID",              type: "text",     ph: "1234567890" },
      { id: "appSecret",   label: "App Secret",          type: "text",     ph: "abc123..." },
      { id: "accessToken", label: "Page Access Token",   type: "text",     ph: "EAABwzLix..." },
      { id: "notes",       label: "Notes",               type: "textarea", ph: "Extra info…" },
    ],
  },
  linkedin: {
    title: "LinkedIn Account",
    fields: [
      { id: "pageUrl",      label: "Page / Profile URL",  type: "text",     ph: "https://linkedin.com/company/yourpage" },
      { id: "email",        label: "Email",               type: "email",    ph: "account@email.com" },
      { id: "password",     label: "Password",            type: "password", ph: "••••••••" },
      { id: "clientId",     label: "OAuth Client ID",     type: "text",     ph: "86abc123def456" },
      { id: "clientSecret", label: "OAuth Client Secret", type: "text",     ph: "WPL_AP1.abc123..." },
      { id: "accessToken",  label: "Access Token",        type: "text",     ph: "AQV... (expires in 60 days)" },
      { id: "refreshToken", label: "Refresh Token",       type: "text",     ph: "AQW..." },
      { id: "orgUrn",       label: "Organization URN",    type: "text",     ph: "urn:li:organization:1234567" },
      { id: "notes",        label: "Notes",               type: "textarea", ph: "Products enabled, review status…" },
    ],
  },
  reddit: {
    title: "Reddit Account",
    fields: [
      { id: "profileUrl",   label: "Profile URL",   type: "text",     ph: "https://reddit.com/u/yourhandle" },
      { id: "username",     label: "Username",      type: "text",     ph: "u/YourHandle" },
      { id: "email",        label: "Email",         type: "email",    ph: "account@email.com" },
      { id: "password",     label: "Password",      type: "password", ph: "••••••••" },
      { id: "clientId",     label: "App Client ID", type: "text",     ph: "abc123XYZ_def" },
      { id: "clientSecret", label: "App Secret",    type: "text",     ph: "xyz789..." },
      { id: "refreshToken", label: "Refresh Token", type: "text",     ph: "123456-abcdef..." },
      { id: "userAgent",    label: "User Agent",    type: "text",     ph: "CreatorNexus/1.0 by u/yourhandle" },
      { id: "notes",        label: "Notes",         type: "textarea", ph: "Subreddits, karma gates, rate limits…" },
    ],
  },
  pinterest: {
    title: "Pinterest Account",
    fields: [
      { id: "profileUrl",   label: "Profile URL",   type: "text",     ph: "https://pinterest.com/yourhandle" },
      { id: "username",     label: "Username",      type: "text",     ph: "YourHandle" },
      { id: "email",        label: "Email",         type: "email",    ph: "account@email.com" },
      { id: "password",     label: "Password",      type: "password", ph: "••••••••" },
      { id: "appId",        label: "App ID",        type: "text",     ph: "1234567" },
      { id: "appSecret",    label: "App Secret",    type: "text",     ph: "abc123..." },
      { id: "accessToken",  label: "Access Token",  type: "text",     ph: "pina_ABC..." },
      { id: "refreshToken", label: "Refresh Token", type: "text",     ph: "pinr_ABC..." },
      { id: "notes",        label: "Notes",         type: "textarea", ph: "Boards, trial vs standard access…" },
    ],
  },
  threads: {
    title: "Threads Account",
    fields: [
      { id: "profileUrl",  label: "Profile URL",           type: "text",     ph: "https://threads.net/@yourhandle" },
      { id: "username",    label: "Username / Handle",     type: "text",     ph: "@YourHandle" },
      { id: "appId",       label: "App ID",                type: "text",     ph: "1234567890" },
      { id: "appSecret",   label: "App Secret",            type: "text",     ph: "abc123..." },
      { id: "accessToken", label: "Access Token",          type: "text",     ph: "THAA... (long-lived, 60 days)" },
      { id: "userId",      label: "Threads User ID",       type: "text",     ph: "987654321" },
      { id: "notes",       label: "Notes",                 type: "textarea", ph: "Login is the Instagram account — see Instagram row" },
    ],
  },
  tumblr: {
    title: "Tumblr Account",
    fields: [
      { id: "blogUrl",          label: "Blog URL",           type: "text",     ph: "https://yourblog.tumblr.com" },
      { id: "username",         label: "Username",           type: "text",     ph: "yourblog" },
      { id: "email",            label: "Email",              type: "email",    ph: "account@email.com" },
      { id: "password",         label: "Password",           type: "password", ph: "••••••••" },
      { id: "consumerKey",      label: "Consumer Key",       type: "text",     ph: "abc123..." },
      { id: "consumerSecret",   label: "Consumer Secret",    type: "text",     ph: "xyz789..." },
      { id: "oauthToken",       label: "OAuth Token",        type: "text",     ph: "abc123..." },
      { id: "oauthTokenSecret", label: "OAuth Token Secret", type: "text",     ph: "xyz789..." },
      { id: "notes",            label: "Notes",              type: "textarea", ph: "OAuth 1.0a — tokens do not expire" },
    ],
  },
  discord: {
    title: "Discord Account",
    fields: [
      { id: "serverUrl",  label: "Server Invite URL", type: "text",     ph: "https://discord.gg/xxxxxx" },
      { id: "guildId",    label: "Server (Guild) ID", type: "text",     ph: "123456789012345678" },
      { id: "appId",      label: "Application ID",    type: "text",     ph: "123456789012345678" },
      { id: "botToken",   label: "Bot Token",         type: "text",     ph: "MTIzNDU2Nzg5..." },
      { id: "webhookUrl", label: "Webhook URL",       type: "text",     ph: "https://discord.com/api/webhooks/…" },
      { id: "channelId",  label: "Channel ID",        type: "text",     ph: "123456789012345678" },
      { id: "notes",      label: "Notes",             type: "textarea", ph: "Bot scopes, channel permissions…" },
    ],
  },
  telegram: {
    title: "Telegram Account",
    fields: [
      { id: "phone",    label: "Phone Number", type: "text",     ph: "+1 555 000 0000" },
      { id: "username", label: "Username",     type: "text",     ph: "@username" },
      { id: "apiId",    label: "API ID",       type: "text",     ph: "12345678" },
      { id: "apiHash",  label: "API Hash",     type: "text",     ph: "abc123..." },
      { id: "botToken", label: "Bot Token",    type: "text",     ph: "123456:ABC-DEF..." },
      { id: "notes",    label: "Notes",        type: "textarea", ph: "Extra info…" },
    ],
  },
  whatsapp: {
    title: "WhatsApp Account",
    fields: [
      { id: "phone",             label: "Phone Number",          type: "text",     ph: "+1 555 000 0000" },
      { id: "businessAccountId", label: "Business Account ID",   type: "text",     ph: "123456789" },
      { id: "phoneNumberId",     label: "Phone Number ID",       type: "text",     ph: "987654321" },
      { id: "accessToken",       label: "Access Token",          type: "text",     ph: "EAABwzLix..." },
      { id: "notes",             label: "Notes",                 type: "textarea", ph: "Extra info…" },
    ],
  },
  vk: {
    title: "VK Account",
    fields: [
      { id: "profileUrl",  label: "Profile / Group URL", type: "text",     ph: "https://vk.com/yourpage" },
      { id: "username",    label: "Username",             type: "text",     ph: "yourpage" },
      { id: "email",       label: "Email",               type: "email",    ph: "account@email.com" },
      { id: "password",    label: "Password",            type: "password", ph: "••••••••" },
      { id: "appId",       label: "App ID",              type: "text",     ph: "12345678" },
      { id: "appSecret",   label: "App Secret",          type: "text",     ph: "abc123..." },
      { id: "accessToken", label: "Access Token",        type: "text",     ph: "vk1.a.abc..." },
      { id: "notes",       label: "Notes",               type: "textarea", ph: "Extra info…" },
    ],
  },
  odnoklassniki: {
    title: "OK.ru Account",
    fields: [
      { id: "profileUrl", label: "Profile URL",   type: "text",     ph: "https://ok.ru/profile/123" },
      { id: "username",   label: "Username",      type: "text",     ph: "yourprofile" },
      { id: "email",      label: "Email",         type: "email",    ph: "account@email.com" },
      { id: "password",   label: "Password",      type: "password", ph: "••••••••" },
      { id: "appId",      label: "App ID",        type: "text",     ph: "12345678901234" },
      { id: "appKey",     label: "Public App Key", type: "text",    ph: "CBAXXX..." },
      { id: "appSecret",  label: "App Secret Key", type: "text",   ph: "FEDCBA..." },
      { id: "notes",      label: "Notes",         type: "textarea", ph: "Extra info…" },
    ],
  },
  rutube: {
    title: "Rutube Account",
    fields: [
      { id: "channelUrl", label: "Channel URL",  type: "text",     ph: "https://rutube.ru/channel/123" },
      { id: "username",   label: "Username",     type: "text",     ph: "yourchannel" },
      { id: "email",      label: "Email",        type: "email",    ph: "account@email.com" },
      { id: "password",   label: "Password",     type: "password", ph: "••••••••" },
      { id: "notes",      label: "Notes",        type: "textarea", ph: "Extra info…" },
    ],
  },
  yandex: {
    title: "Yandex Account",
    fields: [
      { id: "email",        label: "Email",          type: "email",    ph: "yourname@yandex.ru" },
      { id: "password",     label: "Password",       type: "password", ph: "••••••••" },
      { id: "oauthToken",   label: "OAuth Token",    type: "text",     ph: "y0_AgAA..." },
      { id: "notes",        label: "Notes",          type: "textarea", ph: "Extra info…" },
    ],
  },
  bilibili: {
    title: "Bilibili Account",
    fields: [
      { id: "profileUrl", label: "Profile URL",  type: "text",     ph: "https://space.bilibili.com/123" },
      { id: "username",   label: "Username",     type: "text",     ph: "YourChannel" },
      { id: "email",      label: "Email",        type: "email",    ph: "account@email.com" },
      { id: "password",   label: "Password",     type: "password", ph: "••••••••" },
      { id: "phone",      label: "Phone (2FA)",  type: "text",     ph: "+86 000 0000 0000" },
      { id: "notes",      label: "Notes",        type: "textarea", ph: "Extra info…" },
    ],
  },
  sinaweibo: {
    title: "Weibo Account",
    fields: [
      { id: "profileUrl", label: "Profile URL",  type: "text",     ph: "https://weibo.com/yourpage" },
      { id: "username",   label: "Username",     type: "text",     ph: "yourpage" },
      { id: "email",      label: "Email",        type: "email",    ph: "account@email.com" },
      { id: "password",   label: "Password",     type: "password", ph: "••••••••" },
      { id: "appKey",     label: "App Key",      type: "text",     ph: "123456789" },
      { id: "appSecret",  label: "App Secret",   type: "text",     ph: "abc123..." },
      { id: "notes",      label: "Notes",        type: "textarea", ph: "Extra info…" },
    ],
  },
  wechat: {
    title: "WeChat Account",
    fields: [
      { id: "phone",     label: "Phone Number", type: "text",     ph: "+86 000 0000 0000" },
      { id: "appId",     label: "App ID",       type: "text",     ph: "wx1234567890" },
      { id: "appSecret", label: "App Secret",   type: "text",     ph: "abc123..." },
      { id: "notes",     label: "Notes",        type: "textarea", ph: "Extra info…" },
    ],
  },
  qq: {
    title: "QQ Account",
    fields: [
      { id: "qqNumber",  label: "QQ Number",   type: "text",     ph: "123456789" },
      { id: "password",  label: "Password",    type: "password", ph: "••••••••" },
      { id: "appId",     label: "App ID",      type: "text",     ph: "100000000" },
      { id: "appKey",    label: "App Key",     type: "text",     ph: "abc123..." },
      { id: "notes",     label: "Notes",       type: "textarea", ph: "Extra info…" },
    ],
  },
  douyin: {
    title: "Douyin Account",
    fields: [
      { id: "profileUrl", label: "Profile URL",       type: "text",     ph: "https://www.douyin.com/user/xxx" },
      { id: "username",   label: "Username / Handle", type: "text",     ph: "yourhandle" },
      { id: "phone",      label: "Phone",             type: "text",     ph: "+86 000 0000 0000" },
      { id: "appId",      label: "App ID",            type: "text",     ph: "12345" },
      { id: "appSecret",  label: "App Secret",        type: "text",     ph: "abc123..." },
      { id: "notes",      label: "Notes",             type: "textarea", ph: "Extra info…" },
    ],
  },
  zhihu: {
    title: "Zhihu Account",
    fields: [
      { id: "profileUrl", label: "Profile URL", type: "text",     ph: "https://www.zhihu.com/people/xxx" },
      { id: "username",   label: "Username",    type: "text",     ph: "yourprofile" },
      { id: "email",      label: "Email",       type: "email",    ph: "account@email.com" },
      { id: "password",   label: "Password",    type: "password", ph: "••••••••" },
      { id: "notes",      label: "Notes",       type: "textarea", ph: "Extra info…" },
    ],
  },
  youku: {
    title: "Youku Account",
    fields: [
      { id: "channelUrl", label: "Channel URL", type: "text",     ph: "https://i.youku.com/i/xxx" },
      { id: "username",   label: "Username",    type: "text",     ph: "yourchannel" },
      { id: "email",      label: "Email",       type: "email",    ph: "account@email.com" },
      { id: "password",   label: "Password",    type: "password", ph: "••••••••" },
      { id: "notes",      label: "Notes",       type: "textarea", ph: "Extra info…" },
    ],
  },
  iqiyi: {
    title: "iQIYI Account",
    fields: [
      { id: "channelUrl", label: "Channel URL", type: "text",     ph: "https://www.iqiyi.com/u/xxx" },
      { id: "username",   label: "Username",    type: "text",     ph: "yourchannel" },
      { id: "email",      label: "Email",       type: "email",    ph: "account@email.com" },
      { id: "password",   label: "Password",    type: "password", ph: "••••••••" },
      { id: "notes",      label: "Notes",       type: "textarea", ph: "Extra info…" },
    ],
  },
  vital: {
    title: "Other Vital Info",
    fields: [
      { id: "label",    label: "Label",       type: "text",     ph: "e.g. Backup Codes, License Key…" },
      { id: "value",    label: "Value",       type: "textarea", ph: "Paste sensitive data here…" },
      { id: "notes",    label: "Notes",       type: "textarea", ph: "Context or instructions…" },
    ],
  },
};

// ── State ─────────────────────────────────────────────────────────────────────
const state = {
  channels: [],
  selectedChannelId: null,
  openDialogType: null,
};

const expandedChannels = new Set();
let dragState = null;
let activePostPlatformId = POST_PLATFORMS[0].id;

// ── AdSense (global, shared across all channels) ──────────────────────────────
const adsenseState = {
  publisherId: "", email: "", name: "", status: "",
  threshold: "", currency: "", paymentMethod: "", bankAccount: "",
  taxForm: "", taxId: "", country: "",
  balance: "", lastPayment: "", notes: ""
};

function saveAdsense() {
  localStorage.setItem(ADSENSE_KEY, JSON.stringify(adsenseState));
  _cnScheduleSync();
}

function loadAdsense() {
  try {
    const raw = localStorage.getItem(ADSENSE_KEY);
    if (!raw) return;
    const parsed = JSON.parse(raw);
    Object.assign(adsenseState, parsed);
  } catch (e) { /* ignore */ }
}

function initAdsense() {
  loadAdsense();
  const fields = [
    "publisherId", "email", "name", "status",
    "threshold", "currency", "paymentMethod", "bankAccount",
    "taxForm", "taxId", "country",
    "balance", "lastPayment", "notes"
  ];
  fields.forEach(key => {
    const el2 = document.getElementById("ads" + key.charAt(0).toUpperCase() + key.slice(1));
    if (!el2) return;
    el2.value = adsenseState[key] || "";
    el2.addEventListener("input", () => {
      adsenseState[key] = el2.value;
      saveAdsense();
    });
    el2.addEventListener("change", () => {
      adsenseState[key] = el2.value;
      saveAdsense();
    });
  });
}

// ── DOM refs ──────────────────────────────────────────────────────────────────
const el = {
  tabs:             document.querySelectorAll(".tab-chip"),
  panels: {
    channels:  document.getElementById("panel-channels"),
    marketing: document.getElementById("panel-marketing"),
    upload:    document.getElementById("panel-upload"),
    metrics:   document.getElementById("panel-metrics"),
  },
  newChannelName:     document.getElementById("newChannelName"),
  addChannelBtn:      document.getElementById("addChannelBtn"),
  channelList:        document.getElementById("channelList"),
  vaultTitle:         document.getElementById("vaultTitle"),
  channelNameInline:  document.getElementById("channelNameInline"),
  nicheDisplay:       document.getElementById("nicheDisplay"),
  channelNicheInline: document.getElementById("channelNicheInline"),
  usageData:          document.getElementById("usageData"),
  usageApiCalls:      document.getElementById("usageApiCalls"),
  usageTokens:        document.getElementById("usageTokens"),
  saveChannelBtn:     document.getElementById("saveChannelBtn"),
  newDraftBtn:        document.getElementById("newDraftBtn"),
  deleteChannelBtn:   document.getElementById("deleteChannelBtn"),
  settingsBtn:        document.getElementById("settingsBtn"),
  settingsMenu:       document.getElementById("settingsMenu"),
  metricsTableBody:   document.getElementById("metricsTableBody"),
  videoMetricsTableBody: document.getElementById("videoMetricsTableBody"),
  sumChannels:        document.getElementById("sumChannels"),
  sumSubscribers:     document.getElementById("sumSubscribers"),
  sumViews:           document.getElementById("sumViews"),
  sumEngagement:      document.getElementById("sumEngagement"),
  // modal
  modal:       document.getElementById("accountModal"),
  modalTitle:  document.getElementById("modalTitle"),
  modalBody:   document.getElementById("modalBody"),
  modalSave:   document.getElementById("modalSave"),
  modalCancel: document.getElementById("modalCancel"),
  modalClose:  document.getElementById("modalClose"),
  // comments modal
  commentsModal:      document.getElementById("commentsModal"),
  commentsModalTitle: document.getElementById("commentsModalTitle"),
  commentsModalBody:  document.getElementById("commentsModalBody"),
  commentsModalClose: document.getElementById("commentsModalClose"),
  commentsModalDone:  document.getElementById("commentsModalDone"),
};

// ── Helpers ───────────────────────────────────────────────────────────────────
function uid() {
  return crypto.randomUUID ? crypto.randomUUID() : String(Date.now() + Math.random());
}

function emptyAccountData() {
  const ad = {};
  Object.keys(ACCOUNT_DIALOGS).forEach(k => { ad[k] = {}; });
  return ad;
}

function emptyChannel(name = "", parentId = null) {
  return {
    id: uid(),
    name,
    niche: "",
    primaryContact: "",
    parentId,
    subchannels: [],
    accountData: emptyAccountData(),
    usage: { dataUploaded: "", apiCalls: 0, tokensUsed: 0 },
    description: "",
    rules: [],
    policyRules: [],
    generalPolicyRules: [],
    posts: {},
  };
}

// ── Persistence ───────────────────────────────────────────────────────────────
// Guard: a failed or empty load must never overwrite good data. init() calls
// seedAllPolicyRules() -> saveState() on every page load, so without this check
// opening the app once on the wrong origin (or after a parse error) permanently
// replaced the stored channel list with [].
function saveState() {
  if (state.channels.length === 0) {
    const existing = localStorage.getItem(STORAGE_KEY);
    if (existing && existing.trim() !== "[]") {
      console.warn("saveState blocked: refusing to overwrite stored channels with an empty list");
      return;
    }
  }
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state.channels));
  _cnScheduleSync();
}

function migrateOld(ch) {
  if (!ch.accountData) {
    ch.accountData = emptyAccountData();
    if (ch.primaryContact)      ch.accountData.primaryContact.name = ch.primaryContact;
    if (ch.youtubeAccounts)     ch.accountData.youtube.channelUrl   = ch.youtubeAccounts;
    if (ch.facebookAccounts)    ch.accountData.facebook.profileUrl  = ch.facebookAccounts;
    if (ch.googleAccounts)      ch.accountData.google.email         = ch.googleAccounts;
    if (ch.phoneNumbers)        ch.accountData.phone.number         = ch.phoneNumbers;
    if (ch.apiKeys)             ch.accountData.googleCloud.apiKey   = ch.apiKeys;
    if (ch.googleCloudAccounts) ch.accountData.googleCloud.email    = ch.googleCloudAccounts;
    if (ch.emailAddresses)      ch.accountData.email.address        = ch.emailAddresses;
    if (ch.vitalInfo)           ch.accountData.vital.value          = ch.vitalInfo;
    delete ch.primaryContact; delete ch.youtubeAccounts; delete ch.facebookAccounts;
    delete ch.googleAccounts;  delete ch.phoneNumbers;
    delete ch.apiKeys;         delete ch.googleCloudAccounts;
    delete ch.emailAddresses;  delete ch.vitalInfo;
  }
  if (!ch.usage) ch.usage = { dataUploaded: "" };
  if (!ch.subchannels) ch.subchannels = [];
  if (ch.subchannels.length) ch.subchannels = ch.subchannels.map(migrateOld);
  if (ch.description === undefined) ch.description = "";
  if (!ch.rules) ch.rules = [];
  if (!ch.policyRules) ch.policyRules = [];
  if (!ch.generalPolicyRules) ch.generalPolicyRules = [];
  if (!ch.posts) ch.posts = {};
  return ch;
}

// ── YouTube policy rules per channel (seeded on first load, never overwrites) ──
const CHANNEL_POLICY_MAP = {
  // ── Main channels ──────────────────────────────────────────────────────────
  "benchmark": [
    "Each video must include original analysis or commentary — templated benchmark compilations are demonetized under the July 2025 Inauthentic Content Policy.",
    "Disclose all sponsored reviews, affiliate links, or manufacturer relationships on-screen and in the description (FTC Endorsement Guides — up to $51,744 per violation).",
    "Disclose AI-generated narration, visuals, or synthetic media in YouTube Studio 'Altered or Synthetic Content' toggle (YouTube AI Disclosure Policy, May 2025).",
    "Product claims must be factually accurate — avoid misleading performance or health claims about consumer hardware.",
    "Fair use: Use manufacturer footage only briefly and with substantial added commentary; long product demo excerpts without analysis are copyright-infringing.",
    "Avoid excessive profanity in the first 30 seconds and in titles to remain eligible for full ad monetization.",
  ],
  "cars": [
    "Never glorify illegal street racing, reckless driving, or dangerous modifications without clear discouragement messaging in the video audio/visuals.",
    "Disclose any manufacturer-provided vehicles or sponsored drives on-screen and in the description (FTC Endorsement Guides).",
    "Disclose AI-generated visuals or synthetic driving footage using YouTube's 'Altered or Synthetic Content' toggle (AI Disclosure Policy, May 2025).",
    "Include safety warnings in the video itself — not only in the description — for DIY repair, modification, or maintenance content.",
    "Do not reproduce copyrighted OEM service manual text verbatim; use fair use commentary framing around procedural excerpts.",
    "Liability disclaimer in video description for all DIY repair tutorials; disclaim results may vary by vehicle model.",
  ],
  "financials": [
    "Mandatory verbal 'This is not financial advice' disclaimer in every video and in the description — required under YouTube Financial Products Policy.",
    "Disclose all personal holdings, trading positions, or financial interests in any stock, crypto, fund, or property discussed before recommending it.",
    "Never guarantee returns or use language suggesting 'easy money', 'guaranteed profit', or 'can't lose' — triggers removal under Misinformation Policy.",
    "Crypto content: As of November 2025, content framing token staking, yield farming, or trading as investment products is subject to YouTube Gambling Policy restrictions.",
    "Do not create, participate in, or encourage pump-and-dump schemes, coordinated buying, or any market manipulation.",
    "Disclose AI-generated charts, financial simulations, or synthetic market data using YouTube's 'Altered or Synthetic Content' toggle.",
    "Sensitive event coverage (market crashes, economic crises): Frame as educational documentary — 'profiting from or exploiting sensitive events' triggers demonetization.",
  ],
  "news": [
    "All footage must include in-video educational context (audio/visuals) — description-only context is insufficient for EDSA exception eligibility.",
    "Label state media sources (Russian, Chinese broadcasts) on-screen; disclose potential editorial bias explicitly in the video.",
    "Fair use for news clips: Only brief excerpts with substantial commentary, fact-checking, or analysis; bare re-streaming is copyright infringement.",
    "Do not publish content that spreads false information about voting, election procedures, or electoral results (Election Misinformation Policy).",
    "Graphic conflict or violence footage: Only allowed under EDSA exception with clear journalistic framing; footage filmed by perpetrators is never eligible for EDSA exception.",
    "Disclose AI-generated news visuals, synthetic newsreaders, or AI-recreated scenes in YouTube Studio toggle — undisclosed synthetic news media triggers demonetization.",
    "Do not monetize videos that exploit mass casualty events, terrorist attacks, or disasters without clear educational framing (Sensitive Events Advertiser Policy).",
  ],
  "storyteller": [
    "Disclose AI-generated narration that realistically recreates a real human voice using YouTube's 'Altered or Synthetic Content' toggle (AI Disclosure Policy, May 2025).",
    "Each episode must show material variation in plot, character development, or production — templated AI story factories are demonetized under the July 2025 Inauthentic Content Policy.",
    "Never create deepfakes or realistic AI recreations of real people without clear disclosure; unauthorized synthetic likenesses of real persons may violate Harassment Policy.",
    "Ensure all AI-generated characters are clearly depicted as adults; age ambiguity in romantic or intimate storylines is not permitted (Child Safety Policy).",
    "Original character creation only — AI-generated characters must not reproduce copyrighted likenesses, names, or storylines from protected IP without license.",
    "No AI-generated sexual content, even in fictional framing — YouTube prohibits sexually explicit content regardless of synthetic origin.",
  ],
  "arena": [
    "Do not restream full games, broadcasts, halftime shows, or official league productions — direct copyright infringement with no fair use exception.",
    "Highlight clips must be brief, transformative, and accompanied by substantive analytical narration; compilations without commentary are demonetized (Inauthentic Content Policy).",
    "NFL content is extremely restrictive — the NFL actively files Content ID claims; keep clips under 30 seconds and always add play-by-play tactical analysis.",
    "Injury or violent play footage: Provide clear journalistic context; graphic injury footage without framing risks demonetization under Sensitive Events Policy.",
    "Disclose AI-generated visualisations, synthetic match reconstructions, or deepfake athlete footage using YouTube's 'Altered or Synthetic Content' toggle.",
    "Three copyright strikes in any 90-day period results in channel termination — sports is the highest-risk category for Content ID claims.",
    "Obtain permission or licensing for official club/league photography; press imagery is not free-to-use without a license even for commentary purposes.",
  ],
  "tokitoki": [
    "Same core copyright rules as long-form sports: Do not restream broadcasts; all clips must be brief and accompanied by original commentary.",
    "Short-form Shorts: The same fair use test applies — a 15-second highlight without commentary has weaker fair use standing than an analysed clip.",
    "Each Short must be materially unique — templated clip compilations with identical intros/outros are demonetized under the July 2025 Inauthentic Content Policy.",
    "Shorts ad revenue split is 45% creator / 55% YouTube — lower than long-form; ensure content investment is scaled accordingly.",
    "Disclose AI-generated graphics, synthetic stat cards, or deepfake athlete content using YouTube's 'Altered or Synthetic Content' toggle.",
    "Three copyright strikes in 90 days = channel termination; sports clips trigger automated Content ID claims — dispute only with clear fair use justification.",
  ],
  "luxury": [
    "Disclose all sponsored reviews, gifted items, and affiliate/commission links on-screen and in the description (FTC Endorsement Guides — mandatory).",
    "Financial ties to brands (ownership stake, investment, undisclosed partnerships) must be declared before any brand recommendation.",
    "Do not promote, authenticate, or facilitate the sale of counterfeit goods, stolen art, or illegal items — violates Deceptive Practices Policy.",
    "Auction or resale valuations: Disclose qualifications if claiming to authenticate high-value items; misleading valuations risk removal under Misinformation Policy.",
    "Disclose AI-generated product visualisations or synthetic brand imagery using YouTube's 'Altered or Synthetic Content' toggle.",
    "Avoid bait-and-switch tactics (e.g., displaying a replica then switching to an authentic item without disclosure).",
  ],
  "traveling": [
    "Disclose all comped accommodations, sponsored tours, tourism board partnerships, and travel brand relationships on-screen and in description (FTC Endorsement Guides).",
    "Do not create or encourage content that promotes illegal border crossing, visa fraud, or trespassing on restricted land or private property.",
    "Dangerous activities (extreme sports, mountaineering, risky travel): Include in-video discouragement language ('do not attempt without professional training').",
    "Do not publish AI-generated travel scenes or synthetic location footage without disclosing it in YouTube Studio's 'Altered or Synthetic Content' toggle.",
    "Filming restrictions: Respect no-filming rules in museums, temples, mosques, and restricted sites; fair use does not override property rights or religious prohibitions.",
    "Do not exploit or demean indigenous communities, cultural practices, or poverty — provide respectful, contextualised framing at all times.",
    "Minors in travel content: Children must appear in age-appropriate contexts and in the presence of a responsible adult.",
  ],
  "clipped": [
    "Every clip must include substantial original commentary, editorial narration, or analysis — bare compilations with minimal transformation are demonetized (July 2025 Inauthentic Content Policy).",
    "Each video must be materially unique — templated intros, identical transitions, and copy-paste descriptions across uploads flag the channel for demonetization.",
    "Three copyright strikes in 90 days = channel termination — assume all professional clips are rights-protected; dispute claims only with clear fair use justification.",
    "Reaction format is allowed if commentary is meaningful (pausing, reacting, adding insight) — silent or minimal-reaction reposts are removed as inauthentic.",
    "Shorts from Clipped earn a 45% creator revenue share — lower than long-form; transformation quality must justify the lower return.",
    "Disclose any AI editing, enhancement, or synthetic narration overlaid on clips using YouTube's 'Altered or Synthetic Content' toggle.",
    "Consider licensing clips from original creators to avoid Content ID; licensing costs are generally lower than copyright strike consequences.",
  ],
  "crime": [
    "Mandatory EDSA framing: Provide in-video audio/visual context explaining the crime, identifying victims, and stating the public interest — title/description context alone is insufficient.",
    "Do not use AI to deepfake or recreate likenesses of victims, suspects, or perpetrators without explicit disclosure; synthetic recreations of real crime victims may violate Harassment Policy.",
    "Never feature autopsy footage, murder footage, or graphic crime scene imagery under any circumstances — these are never eligible for EDSA exception.",
    "Do not encourage vigilante justice, suspect doxxing, or interference with active police investigations.",
    "Victims must be treated with dignity — do not exploit the family members or trauma of crime victims for entertainment or sensationalism.",
    "Minors involved in crime (as perpetrators or victims): Do not feature in graphic detail; any juvenile criminal content requires age-gating and must have comments disabled.",
    "Monetisation: Content 'profiting from or exploiting sensitive events' faces demonetisation — maintain strict documentary tone, not sensationalism.",
  ],
  "docudocu": [
    "Each documentary must show materially different approach, sources, or narrative — templated AI documentary factories are demonetised under the July 2025 Inauthentic Content Policy.",
    "Cite all sources, interviewees, archival footage origins, and expert credentials in the video or description.",
    "Do not present speculation, contested theories, or fringe science as established fact — distinguish between proven science, peer-reviewed research, and hypothesis.",
    "Fair use: Archived footage is stronger for fair use with substantial original narration and transformative framing; obtain permissions where possible.",
    "Medical content: Do not discourage viewers from seeking approved medical treatment or promote unproven cures — triggers Medical Misinformation Policy removal.",
    "Historical accuracy: Include counter-evidence or acknowledged debate when covering contested historical events; avoid spreading disproven claims.",
    "Disclose AI-generated narration recreating real people's voices using YouTube's 'Altered or Synthetic Content' toggle; simple AI text-to-speech does not require disclosure.",
  ],
  "religion": [
    "Religious criticism is permitted under free expression, but content that incites hatred of groups based on religion violates YouTube's Hate Speech Policy — removal + channel strike.",
    "Animal sacrifice, ritual, or ceremony footage: Must include clear in-video educational/cultural context explaining significance; avoid gratuitous or sensationalist framing (EDSA Policy).",
    "Do not create misleading content designed to recruit viewers into harmful cults, financially exploitative organisations, or abusive spiritual communities.",
    "Spiritual healing or miracle claims: Disclose that treatments are unproven; never discourage viewers from seeking medical care — violates Medical Misinformation Policy.",
    "Filming sacred sites: Respect no-filming prohibitions; obtain permission before filming inside temples, mosques, or churches; disclose if access was denied.",
    "Copyright for religious texts: Public domain texts (Bible, Quran, Torah, Vedas via Project Gutenberg) may be used freely; modern translations may be copyrighted — verify before use.",
    "Content glorifying religious extremism, violence, or terrorism is demonetised regardless of framing.",
  ],

  // ── Subchannels: Benchmark ─────────────────────────────────────────────────
  "phones": [
    "Add original testing methodology, real-world usage commentary, or comparative analysis — raw spec recitation without insight is classified as inauthentic content.",
    "Disclose if a device was provided by the manufacturer or carrier (FTC Endorsement Guides); 'gifted' devices must be disclosed even if no payment was made.",
    "Disclose AI-generated visuals, renders, or synthetic product footage using YouTube's 'Altered or Synthetic Content' toggle.",
    "Use manufacturer press images only within fair use (transformative commentary); do not reproduce entire press kits without license.",
    "Avoid absolute superlative claims ('best camera ever') without substantiated testing data; misleading performance claims risk Misinformation Policy action.",
  ],
  "gpus": [
    "Original benchmark methodology and analysis required — templated GPU spec readouts without commentary are demonetised under Inauthentic Content Policy.",
    "Disclose any hardware provided by Nvidia, AMD, or Intel, or any financial relationship with hardware vendors (FTC Endorsement Guides).",
    "Disclose AI-generated benchmark visualisations or synthetic performance graphs using YouTube's 'Altered or Synthetic Content' toggle.",
    "Fair use: Official press renders and product images require transformative commentary; mere display of press imagery without analysis is not fair use.",
    "Power/thermal data: Do not present theoretical TDP as real-world measurement without clarifying the distinction.",
  ],
  "large language models": [
    "Disclose AI-generated evaluation content (e.g., AI-narrated model comparisons) using YouTube's 'Altered or Synthetic Content' toggle — this category has heightened scrutiny.",
    "Add original analysis beyond benchmark scores — templated LLM tier lists without substantive commentary are demonetised under Inauthentic Content Policy.",
    "Disclose any financial relationship with AI companies (API credits, sponsorships, equity) whose models are featured (FTC Endorsement Guides).",
    "Do not misrepresent AI capability benchmarks as definitive truth — acknowledge methodological limitations and testing conditions.",
    "Avoid presenting AI safety reports selectively in a misleading way; provide balanced context or link to full model cards.",
  ],
  "future cars": [
    "Official manufacturer press releases and render images are generally provided for press use; confirm licensing terms before publishing.",
    "Disclose AI-generated concept renders or synthetic vehicle visualisations using YouTube's 'Altered or Synthetic Content' toggle.",
    "Do not publish unverified leaked specs as confirmed fact; clearly label unverified information as rumour or speculation.",
    "Motor show coverage: Convention centre or event footage may be subject to media credential restrictions — confirm filming permissions.",
    "Avoid definitive price predictions or range claims that could be construed as financial advice about vehicle investments.",
  ],
  "oldtimers": [
    "Auction result data (Barrett-Jackson, RM Sotheby's) is generally public record; cite the auction source for each result.",
    "Period photography may be public domain or archival — verify copyright status before use; images after 1928 (US) or 1954 (EU) may still be protected.",
    "Do not present restoration cost estimates as guaranteed quotes; disclaim that costs vary significantly by vehicle condition and region.",
    "Disclose if featuring vehicles or collections that are personally owned, commercially affiliated, or sponsor-provided.",
    "Fair use: Brief archival footage of vintage vehicles with substantial narration and historical context is generally supportable as fair use.",
  ],
  "car mechanics": [
    "Include safety warnings in the video itself (not just description) for all repair procedures involving hazardous materials, high voltage, or heavy components.",
    "Do not reproduce OEM service manual procedures verbatim — use fair use commentary framing around technical steps; link to official manuals where available.",
    "Include liability disclaimer in every video description: results, tolerances, and risks vary by vehicle model and year.",
    "Disclose if any tools, parts, or products featured were provided by suppliers or sponsors (FTC Endorsement Guides).",
    "Do not feature minors performing hazardous repairs on camera (Child Safety Policy).",
  ],
  "wyscamus": [
    "Mandatory verbal 'This is not financial advice' disclaimer in video and description — editorial commentary does not exempt from YouTube Financial Products Policy.",
    "Disclose any personal market positions, fund investments, or financial interests in companies or assets discussed.",
    "Do not present macro-economic opinion as objective fact; clearly frame content as editorial analysis.",
    "Disclose AI-generated economic charts, synthetic data visualisations, or AI-written commentary using YouTube's 'Altered or Synthetic Content' toggle.",
    "Sensitive event coverage (recessions, banking crises): Frame as educational documentary; exploiting financial crises without context risks demonetisation.",
  ],
  "stockmarket": [
    "Mandatory 'This is not financial advice' disclaimer verbally in video and in description (YouTube Financial Products Policy).",
    "Disclose all personal stock holdings, options positions, or financial ties to any company discussed before making commentary.",
    "Never use language guaranteeing returns, predicting exact price targets as certainty, or framing stock picks as 'can't lose' investments.",
    "Do not encourage, coordinate, or allude to coordinated buying or selling activity (market manipulation).",
    "Earnings report analysis: Disclose if data sourced from SEC EDGAR or third-party; do not present preliminary estimates as confirmed results.",
    "Disclose AI-generated market charts or synthetic financial data visualisations using YouTube's 'Altered or Synthetic Content' toggle.",
  ],
  "cryptodaily": [
    "Mandatory 'This is not financial advice' disclaimer in every video and description (YouTube Financial Products Policy).",
    "Disclose all personal crypto holdings and any financial ties to blockchain projects, exchanges, or token issuers featured.",
    "As of November 2025: Content framing token staking, DeFi yield, or trading as investment products is subject to YouTube Gambling Policy restrictions.",
    "Never promote, imply, or facilitate pump-and-dump schemes, coordinated wallet activity, or artificial token price inflation.",
    "Regulatory news: Do not present regulatory speculation as confirmed law; label all pending regulatory developments as unconfirmed.",
    "Disclose AI-generated on-chain metric visualisations or synthetic price chart animations using YouTube's 'Altered or Synthetic Content' toggle.",
  ],
  "housing": [
    "Mandatory 'This is not financial advice' disclaimer in video and description — housing market commentary is covered by YouTube Financial Products Policy.",
    "Disclose any personal real estate holdings, investment properties, or financial interest in markets or regions discussed.",
    "Regional price index data (Zillow, Case-Shiller): Cite the source in the video or description; do not present third-party data as independently verified.",
    "Mortgage rate predictions: Frame as estimates based on available data — do not present as guaranteed forecasts.",
    "Disclose AI-generated housing market visualisations or synthetic infographics using YouTube's 'Altered or Synthetic Content' toggle.",
  ],
  "developmental landplots": [
    "Mandatory 'This is not financial advice' disclaimer in video and description — land investment commentary falls under YouTube Financial Products Policy.",
    "Disclose any personal ownership, brokerage, or financial interest in land or development projects discussed.",
    "Zoning and planning data: Cite local government sources; note that planning data changes frequently and viewers must verify current status independently.",
    "Aerial or satellite imagery (Google Maps Static API, etc.) is subject to Google's Terms of Service — do not reproduce at scale or for commercial resale.",
    "Do not present development timelines or projected land values as guaranteed outcomes; disclaim that development plans are subject to approval and change.",
  ],
  "world": [
    "All footage must have in-video EDSA context (audio/visuals) — description-only context does not satisfy EDSA exception requirements.",
    "Graphic conflict or war footage: Provide clear journalistic framing; footage filmed by perpetrators during lethal attacks is never eligible for EDSA exception.",
    "Do not publish election misinformation — false claims about voting procedures, results, or eligibility (Election Misinformation Policy).",
    "Disclose AI-generated news visuals or synthetic newsreader footage using YouTube's 'Altered or Synthetic Content' toggle.",
    "Do not monetise videos exploiting mass casualty events, terrorism, or disasters without clear educational documentary framing.",
    "Cite all news wire sources (Reuters, AP, AFP) on-screen or in description; sourcing transparency strengthens fair use claim for clips.",
  ],
  "russian": [
    "Label all Russian state media sources (TASS, RT) clearly on-screen; disclose potential editorial bias in the video itself, not just in the description.",
    "Dual-perspective coverage: When including state media material, balance with independent reporting (Meduza, Reuters) to avoid being classified as state-media amplification.",
    "All footage must have in-video EDSA context for graphic or conflict-related content — description context alone is insufficient.",
    "Do not publish election misinformation or false information about geopolitical events as fact (Misinformation Policy).",
    "Disclose AI-generated visuals, synthetic newsreaders, or AI-recreated scenes using YouTube's 'Altered or Synthetic Content' toggle.",
    "Russian-language content serving Russian audiences: YouTube's monetisation availability for Russian-region content may be restricted — verify current availability.",
  ],
  "western": [
    "Provide balanced sourcing across AP, Reuters, and BBC; single-source dependency weakens editorial credibility and may flag under Misinformation Policy.",
    "All footage must have in-video EDSA context for sensitive event coverage — description-only context is insufficient.",
    "Do not spread false information about voting, electoral procedures, or political candidates (Election Misinformation Policy).",
    "Fair use for news clips: Add substantial commentary and analysis; brief excerpts with minimal narration have weaker fair use standing.",
    "Disclose AI-generated visuals or synthetic news content using YouTube's 'Altered or Synthetic Content' toggle.",
  ],
  "europe": [
    "GDPR compliance note: If collecting viewer data or using analytics beyond YouTube's built-in tools, ensure compliance with EU GDPR regulations.",
    "All footage must have in-video EDSA context for sensitive event coverage — description-only context is insufficient.",
    "Euronews and Politico Europe content: Verify fair use rights — transformative commentary is required; bare clip reproduction is infringement.",
    "Do not spread false information about EU elections, voting procedures, or electoral results (Election Misinformation Policy).",
    "Disclose AI-generated visuals or synthetic news content using YouTube's 'Altered or Synthetic Content' toggle.",
  ],
  "china": [
    "Label all Chinese state media sources (Xinhua, CGTN) clearly on-screen with disclosure of editorial bias within the video itself.",
    "Balance state media sources with independent reporting (SCMP, Reuters) — sole reliance on Xinhua may be classified as state-media amplification.",
    "All footage must have in-video EDSA context for sensitive event coverage; conflict or protest footage requires clear journalistic framing.",
    "Do not publish unverified government claims as confirmed fact; label Chinese official statements as official government position.",
    "Disclose AI-generated visuals or synthetic news recreations using YouTube's 'Altered or Synthetic Content' toggle.",
  ],
  "south america": [
    "Cite all Latin American sources (Mercopress, Reuters LatAm, Infobae) in-video or in description; source transparency supports fair use claims.",
    "All footage must have in-video EDSA context for sensitive event coverage — description-only context is insufficient.",
    "Do not publish election misinformation about South American electoral processes (Election Misinformation Policy).",
    "Corruption or crime reporting: Frame as journalistic investigation, not entertainment; provide context and protect vulnerable sources.",
    "Disclose AI-generated visuals or synthetic news content using YouTube's 'Altered or Synthetic Content' toggle.",
  ],
  "her stories": [
    "Disclose AI-generated narration that realistically recreates a real human voice using YouTube's 'Altered or Synthetic Content' toggle.",
    "Every episode must show materially different plot, character arc, or production approach — templated AI story outputs are demonetised (Inauthentic Content Policy, July 2025).",
    "All AI-generated characters must be clearly depicted as adults in any romantic or intimate storyline — age ambiguity is not permitted (Child Safety Policy).",
    "Do not create AI likenesses of real, identifiable people without clear disclosure; realistic synthetic persons may violate Harassment Policy.",
    "Emotionally distressing narratives (abuse, trauma, loss): Frame sensitively and include viewer discretion notice in description.",
  ],
  "his stories": [
    "Disclose AI-generated narration that realistically recreates a real human voice using YouTube's 'Altered or Synthetic Content' toggle.",
    "Every episode must show materially different plot, character arc, or production approach — templated AI story outputs are demonetised (Inauthentic Content Policy, July 2025).",
    "All AI-generated characters must be clearly depicted as adults in any romantic or intimate storyline — age ambiguity is not permitted (Child Safety Policy).",
    "Do not create AI likenesses of real, identifiable people without clear disclosure; realistic synthetic persons may violate Harassment Policy.",
    "Emotionally distressing narratives (abuse, trauma, loss): Frame sensitively and include viewer discretion notice in description.",
  ],
  "made up stories": [
    "Fully generative content still subject to Inauthentic Content Policy — each story must be materially unique, not a templated output.",
    "No sexual content, even in fictional framing — AI-generated sexual content violates YouTube policies regardless of synthetic origin.",
    "Disclose AI-generated narration that realistically recreates a real human voice using YouTube's 'Altered or Synthetic Content' toggle.",
    "Do not reference, imitate, or satirise real identifiable individuals without disclosure — synthetic likenesses of real people may violate Harassment Policy.",
    "Original characters and plots only — do not reproduce storylines or characters from copyrighted IP (books, films, games) without license.",
  ],
  "soccer": [
    "Do not restream full match broadcasts, league productions, or halftime shows — direct copyright infringement with no fair use exception.",
    "Highlight clips must be brief (under 30 seconds), transformative, and accompanied by substantive tactical or journalistic narration.",
    "Official club and UEFA/FIFA photography requires licensing — press imagery is not free to use for commercial content without a license.",
    "Disclose AI-generated match reconstructions, synthetic player footage, or deepfake athlete content using YouTube's 'Altered or Synthetic Content' toggle.",
    "Three copyright strikes in 90 days = channel termination — football is the highest-risk sport for Content ID claims globally.",
  ],
  "nba": [
    "NBA Stats API data is publicly available; cite the source and do not misrepresent official statistics.",
    "Do not restream full game broadcasts, NBA League Pass content, or official NBA productions — direct copyright infringement.",
    "Highlight clips must be brief, accompanied by original play-by-play or analytical commentary; compilations without narration are demonetised.",
    "Official NBA photography requires licensing — do not use NBA press photos commercially without a license.",
    "Disclose AI-generated visualisations or synthetic player footage using YouTube's 'Altered or Synthetic Content' toggle.",
    "Three copyright strikes in 90 days = channel termination — NBA actively files Content ID claims.",
  ],
  "ufc": [
    "Do not restream full UFC events, PPV broadcasts, or official UFC productions — ESPN and UFC own exclusive broadcast rights.",
    "Violence in UFC content is permitted in a sports journalism context (EDSA), but gratuitous injury footage without analytical framing risks demonetisation.",
    "Highlight clips must be brief and accompanied by substantial tactical or journalistic commentary; bare fight clip compilations are demonetised.",
    "Fighter press photos require licensing from UFC's official press kit — they are not freely available for commercial use.",
    "Disclose AI-generated fight reconstructions or synthetic athlete footage using YouTube's 'Altered or Synthetic Content' toggle.",
    "Three copyright strikes in 90 days = channel termination — UFC aggressively files Content ID claims for fight footage.",
  ],
  "tennis": [
    "Do not restream live ATP/WTA matches or Grand Slam broadcasts — rights holders (ESPN, beIN Sports, Eurosport) actively enforce Content ID.",
    "Match highlight clips must be brief and accompanied by substantial analytical or journalistic commentary.",
    "Official tournament photography (Grand Slams, ATP/WTA tour) requires licensing — press imagery is not free for commercial use.",
    "Disclose AI-generated match reconstructions or synthetic player footage using YouTube's 'Altered or Synthetic Content' toggle.",
    "Three copyright strikes in 90 days = channel termination — tennis broadcast rights holders actively file Content ID claims.",
  ],
  "nfl": [
    "NFL content carries the strictest broadcast copyright of any US sport — the NFL actively files Content ID and DMCA claims on all highlight clips.",
    "Keep all NFL game footage under 30 seconds; always overlay with substantive play-by-play or tactical narration to support fair use.",
    "Do not restream games, NFL Network, Thursday Night Football, or any official NFL production — direct infringement with no EDSA exception.",
    "Official NFL team photography requires licensing — team logos and jersey designs are also trademarked and restricted for commercial use.",
    "Disclose AI-generated play reconstructions or synthetic player footage using YouTube's 'Altered or Synthetic Content' toggle.",
    "Three copyright strikes in 90 days = channel termination — treat every NFL clip as a potential Content ID trigger.",
  ],
};

function seedPolicyRules(ch) {
  if (!ch.policyRules || ch.policyRules.length > 0) return;
  const key = (ch.name || "").toLowerCase().trim();
  const rules = CHANNEL_POLICY_MAP[key];
  if (rules) ch.policyRules = [...rules];
}

function seedGeneralPolicyRules(ch) {
  if (!ch.generalPolicyRules || ch.generalPolicyRules.length > 0) return;
  ch.generalPolicyRules = [...GENERAL_POLICY_RULES];
}

function seedAllPolicyRules() {
  state.channels.forEach(ch => {
    seedPolicyRules(ch);
    seedGeneralPolicyRules(ch);
    (ch.subchannels || []).forEach(sub => {
      seedPolicyRules(sub);
      seedGeneralPolicyRules(sub);
    });
  });
  if (state.channels.length > 0) saveState();
}

function loadState() {
  // "[]" is a truthy string, so a previously-written empty list would mask the
  // v1 fallback forever. Treat it as a miss.
  let raw = localStorage.getItem(STORAGE_KEY);
  if (!raw || raw.trim() === "[]") raw = localStorage.getItem("creator_nexus_channels_v1");
  if (!raw) return;
  try {
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed)) {
      state.channels = parsed.map(migrateOld);
      if (state.channels.length > 0) state.selectedChannelId = state.channels[0].id;
    }
  } catch (e) { console.error("Failed to load state", e); }
}

// ── Summaries ─────────────────────────────────────────────────────────────────
function summaryFor(type, data) {
  if (!data || !Object.values(data).some(v => v && String(v).trim())) return null;
  const cfg = ACCOUNT_DIALOGS[type];
  const firstField = cfg.fields[0];
  const v = data[firstField.id];
  return v ? String(v) : "Configured";
}

function updateSummaries(channel) {
  Object.keys(ACCOUNT_DIALOGS).forEach(type => {
    const el2 = document.getElementById(`sum-${type}`);
    if (!el2) return;
    const summary = summaryFor(type, channel?.accountData?.[type]);
    if (summary) {
      el2.textContent = summary;
      el2.classList.add("configured");
    } else {
      el2.textContent = "Not configured";
      el2.classList.remove("configured");
    }
  });
}

// ── Form fill / clear ─────────────────────────────────────────────────────────
function clearForm() {
  el.vaultTitle.textContent = "Select a Channel";
  el.vaultTitle.style.display = "";
  el.channelNameInline.style.display = "none";
  el.nicheDisplay.textContent = "—";
  el.nicheDisplay.style.display = "";
  el.channelNicheInline.style.display = "none";
  el.usageData.value = "";
  updateSummaries(null);
}

function fillForm(channel) {
  if (!channel) { clearForm(); return; }
  el.vaultTitle.textContent = channel.name || "Untitled Channel";
  el.vaultTitle.style.display = "";
  el.channelNameInline.style.display = "none";
  el.nicheDisplay.textContent = channel.niche || "No niche set — click to add";
  el.nicheDisplay.style.display = "";
  el.channelNicheInline.style.display = "none";
  el.usageData.value = channel.usage?.dataUploaded || "";
  updateSummaries(channel);
  renderDescriptionTab(channel);
  renderPostsTab(channel);
}

function renderDescriptionTab(channel) {
  const descEl = document.getElementById("channelDescription");
  if (!descEl) return;

  descEl.value = channel.description || "";
  descEl.oninput = () => {
    channel.description = descEl.value;
    saveState();
  };

  renderRulesList(channel, "rules", document.getElementById("rulesList"));
  renderRulesList(channel, "policyRules", document.getElementById("policyRulesList"));
  renderRulesList(channel, "generalPolicyRules", document.getElementById("generalPolicyRulesList"));
}

// ── Posts tab ─────────────────────────────────────────────────────────────────
function renderPostsTab(channel) {
  const bar    = document.getElementById("postsBar");
  const panels = document.getElementById("postsPanels");
  if (!bar || !panels) return;

  activePostPlatformId = POST_PLATFORMS[0].id;

  bar.innerHTML = POST_PLATFORMS.map((p, i) => `
    <button class="platform-tab posts-ptab${i === 0 ? " active" : ""}" data-postplatform="${p.id}" type="button" title="${p.title}" style="--pc:#${p.color}">
      <img src="https://cdn.simpleicons.org/${p.slug}/${p.color}" alt="${p.title}" width="20" height="20">
    </button>`).join("");

  bar.querySelectorAll(".posts-ptab").forEach(tab => {
    tab.addEventListener("click", () => {
      bar.querySelectorAll(".posts-ptab").forEach(t => t.classList.remove("active"));
      tab.classList.add("active");
      activePostPlatformId = tab.dataset.postplatform;
      renderPostsKanban(channel, activePostPlatformId);
    });
  });

  renderPostsKanban(channel, activePostPlatformId);
}

function makePostCardHTML(post) {
  const STATUS_LABELS = { idea: "Idea", draft: "Draft", ready: "Ready", posted: "Posted" };
  return `<div class="content-card" data-postid="${post.id}" title="Click to edit">
    <div class="content-card-title">${escHtml(post.title || "(Untitled)")}</div>
    <div class="content-card-stats">
      <div class="stat-row">
        <span class="stat-label">Status</span>
        <span class="stat-value">${STATUS_LABELS[post.status] || post.status}</span>
      </div>
      <div class="stat-row">
        <span class="stat-label">Date</span>
        <span class="stat-value">${post.date || "—"}</span>
      </div>
    </div>
  </div>`;
}

function renderPostsKanban(channel, platformId) {
  const panels = document.getElementById("postsPanels");
  if (!panels) return;
  if (!channel.posts) channel.posts = {};
  if (!channel.posts[platformId]) channel.posts[platformId] = [];
  const posts = channel.posts[platformId];

  const PREVIEW_CARDS = {
    idea:   { id: "__preview__", title: "Preview Post Title", status: "idea",   date: "" },
    draft:  { id: "__preview__", title: "Preview Post Title", status: "draft",  date: "" },
    ready:  { id: "__preview__", title: "Preview Post Title", status: "ready",  date: "" },
    posted: { id: "__preview__", title: "Preview Post Title", status: "posted", date: "" },
  };

  panels.innerHTML = `<div class="posts-kanban">${POST_COLS.map(col => {
    const colPosts = posts.filter(p => p.status === col.id);
    const previewHTML = colPosts.length === 0
      ? `<div class="content-card posts-preview-card" data-addcol="${col.id}">
           <div class="content-card-title posts-preview-title">Preview Post Title</div>
         </div>`
      : "";
    return `<div class="posts-col">
      <div class="content-col-header">
        ${col.label}${colPosts.length ? `<span class="posts-col-count">${colPosts.length}</span>` : ""}
        <button class="posts-col-add-btn" data-col="${col.id}" type="button" title="Add post">+</button>
      </div>
      <div class="posts-cards-list">
        ${previewHTML}
        ${colPosts.map(makePostCardHTML).join("")}
      </div>
    </div>`;
  }).join("")}</div>`;

  panels.querySelectorAll(".content-card[data-postid]").forEach(card => {
    card.addEventListener("click", () => openPostModal(channel, platformId, card.dataset.postid, null));
  });
  panels.querySelectorAll(".posts-preview-card[data-addcol]").forEach(card => {
    card.addEventListener("click", () => openPostModal(channel, platformId, null, card.dataset.addcol));
  });
  panels.querySelectorAll(".posts-col-add-btn").forEach(btn => {
    btn.addEventListener("click", () => openPostModal(channel, platformId, null, btn.dataset.col));
  });
}

function openPostModal(channel, platformId, postId, defaultStatus) {
  const modal    = document.getElementById("postModal");
  const delBtn   = document.getElementById("postModalDelete");
  const isNew    = !postId;

  let post;
  if (isNew) {
    post = { id: uid(), title: "", body: "", status: defaultStatus || "idea", date: "" };
  } else {
    post = (channel.posts[platformId] || []).find(p => p.id === postId);
    if (!post) return;
  }

  document.getElementById("postModalPlatform").textContent =
    POST_PLATFORMS.find(p => p.id === platformId)?.title || platformId;
  document.getElementById("postModalTitle").value  = post.title;
  document.getElementById("postModalBody").value   = post.body;
  document.getElementById("postModalStatus").value = post.status;
  document.getElementById("postModalDate").value   = post.date;

  delBtn.hidden = isNew;
  modal._post       = post;
  modal._isNew      = isNew;
  modal._channel    = channel;
  modal._platformId = platformId;
  modal.classList.add("open");
}

function closePostModal() {
  document.getElementById("postModal").classList.remove("open");
}

function savePostModal() {
  const modal      = document.getElementById("postModal");
  const channel    = modal._channel;
  const platformId = modal._platformId;
  const post       = modal._post;
  const isNew      = modal._isNew;

  if (!channel || !platformId || !post) {
    console.error("savePostModal: missing context", { channel, platformId, post });
    return;
  }

  post.title  = document.getElementById("postModalTitle").value.trim();
  post.body   = document.getElementById("postModalBody").value;
  post.status = document.getElementById("postModalStatus").value;
  post.date   = document.getElementById("postModalDate").value;

  if (!channel.posts) channel.posts = {};
  if (!channel.posts[platformId]) channel.posts[platformId] = [];
  if (isNew) {
    channel.posts[platformId].push(post);
  } else {
    const idx = channel.posts[platformId].findIndex(p => p.id === post.id);
    if (idx !== -1) channel.posts[platformId][idx] = post;
  }
  saveState();
  closePostModal();
  renderPostsKanban(channel, platformId);
}

function deletePostModal() {
  const modal     = document.getElementById("postModal");
  const channel   = modal._channel;
  const platformId = modal._platformId;
  const postId    = modal._post.id;

  if (channel.posts[platformId]) {
    channel.posts[platformId] = channel.posts[platformId].filter(p => p.id !== postId);
  }
  saveState();
  closePostModal();
  renderPostsKanban(channel, platformId);
}

function renderRulesList(channel, key, listEl) {
  if (!listEl) return;
  listEl.innerHTML = "";
  (channel[key] || []).forEach((rule, idx) => {
    const item = document.createElement("div");
    item.className = "desc-rule-item";
    item.innerHTML = `
      <span class="desc-rule-num">${idx + 1}</span>
      <span class="desc-rule-text" contenteditable="true" spellcheck="false">${escHtml(rule)}</span>
      <button class="desc-rule-del" type="button" title="Delete rule">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" width="12" height="12"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
      </button>`;
    const textEl = item.querySelector(".desc-rule-text");
    textEl.addEventListener("input", () => {
      channel[key][idx] = textEl.textContent.trim();
      saveState();
    });
    textEl.addEventListener("keydown", e => {
      if (e.key === "Enter") { e.preventDefault(); textEl.blur(); }
    });
    item.querySelector(".desc-rule-del").addEventListener("click", () => {
      channel[key].splice(idx, 1);
      saveState();
      renderRulesList(channel, key, listEl);
    });
    listEl.appendChild(item);
  });
}

function escHtml(str) {
  return String(str).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
}

function addRuleToList(key, listId) {
  const channel = getSelectedChannel();
  const listEl = document.getElementById(listId);
  if (!channel || !listEl) return;

  listEl.querySelectorAll(".desc-rule-input-row").forEach(r => r.remove());

  const row = document.createElement("div");
  row.className = "desc-rule-input-row";

  const numSpan = document.createElement("span");
  numSpan.className = "desc-rule-num";
  numSpan.textContent = (channel[key] || []).length + 1;

  const inp = document.createElement("input");
  inp.type = "text";
  inp.className = "desc-rule-input";
  inp.placeholder = "Type a rule and press Enter…";
  inp.maxLength = 200;

  row.appendChild(numSpan);
  row.appendChild(inp);
  listEl.appendChild(row);

  let committed = false;
  function commit() {
    if (committed) return;
    committed = true;
    const val = inp.value.trim();
    if (val) {
      if (!channel[key]) channel[key] = [];
      channel[key].push(val);
      saveState();
    }
    renderRulesList(channel, key, listEl);
  }

  inp.addEventListener("keydown", e => {
    if (e.key === "Enter") { e.preventDefault(); inp.blur(); }
    if (e.key === "Escape") { committed = true; row.remove(); }
  });
  inp.addEventListener("blur", commit);

  // Defer focus past the current click event to avoid immediate blur race
  requestAnimationFrame(() => inp.focus());
}

// ── Collect ───────────────────────────────────────────────────────────────────
function collectFormData() {
  return {};
}

function saveChannel() {
  const channel = getSelectedChannel();
  if (!channel) return;
  saveState();
  renderChannelList();
  renderMetrics();
}
function getSelectedChannel() {
  for (const ch of state.channels) {
    if (ch.id === state.selectedChannelId) return ch;
    if (ch.subchannels) {
      const sub = ch.subchannels.find(s => s.id === state.selectedChannelId);
      if (sub) return sub;
    }
  }
  return null;
}

function renderChannelList() {
  el.channelList.innerHTML = "";
  if (state.channels.length === 0) {
    const p = document.createElement("p");
    p.textContent = "No channels yet. Add one to begin.";
    p.style.cssText = "color:#9bb1cf;font-size:0.9rem;";
    el.channelList.appendChild(p);
    return;
  }

  function makeDragHandle() {
    const h = document.createElement("span");
    h.className = "drag-handle";
    h.innerHTML = `<svg viewBox="0 0 10 16" fill="currentColor" width="8" height="13"><circle cx="3" cy="2.5" r="1.5"/><circle cx="7" cy="2.5" r="1.5"/><circle cx="3" cy="8" r="1.5"/><circle cx="7" cy="8" r="1.5"/><circle cx="3" cy="13.5" r="1.5"/><circle cx="7" cy="13.5" r="1.5"/></svg>`;
    return h;
  }

  function clearDropIndicators(selector) {
    document.querySelectorAll(selector).forEach(n => n.classList.remove("drag-over-top", "drag-over-bottom"));
  }

  state.channels.forEach(channel => {
    const wrap = document.createElement("div");
    wrap.className = "channel-item-wrap";
    wrap.draggable = true;

    const row = document.createElement("div");
    row.className = "channel-pill-row";

    // ── Main channel drag ──
    wrap.addEventListener("dragstart", e => {
      dragState = { type: "channel", id: channel.id };
      e.dataTransfer.effectAllowed = "move";
      setTimeout(() => wrap.classList.add("dragging"), 0);
    });
    wrap.addEventListener("dragend", () => {
      wrap.classList.remove("dragging");
      dragState = null;
      clearDropIndicators(".channel-item-wrap");
    });
    wrap.addEventListener("dragover", e => {
      if (!dragState || dragState.type !== "channel") return;
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
      clearDropIndicators(".channel-item-wrap");
      const rect = row.getBoundingClientRect();
      wrap.classList.add(e.clientY < rect.top + rect.height / 2 ? "drag-over-top" : "drag-over-bottom");
    });
    wrap.addEventListener("dragleave", e => {
      if (!wrap.contains(e.relatedTarget)) wrap.classList.remove("drag-over-top", "drag-over-bottom");
    });
    wrap.addEventListener("drop", e => {
      e.preventDefault();
      if (!dragState || dragState.type !== "channel" || dragState.id === channel.id) return;
      const fromIdx = state.channels.findIndex(c => c.id === dragState.id);
      if (fromIdx === -1) return;
      const [moved] = state.channels.splice(fromIdx, 1);
      let insertAt = state.channels.findIndex(c => c.id === channel.id);
      if (insertAt === -1) { state.channels.push(moved); }
      else {
        const rect = row.getBoundingClientRect();
        if (e.clientY >= rect.top + rect.height / 2) insertAt++;
        state.channels.splice(insertAt, 0, moved);
      }
      saveState();
      renderChannelList();
    });

    // ── Main channel row content ──
    row.appendChild(makeDragHandle());

    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "channel-pill" + (channel.id === state.selectedChannelId ? " active" : "");
    const nameLbl = document.createElement("span");
    nameLbl.textContent = channel.name || "Untitled Channel";
    btn.appendChild(nameLbl);
    btn.addEventListener("click", () => {
      state.selectedChannelId = channel.id;
      fillForm(channel);
      renderChannelList();
      openSubtab("content");
      _refreshYtPanelsForChannel();
    });

    const hasSubs = channel.subchannels && channel.subchannels.length > 0;
    const isCollapsed = !expandedChannels.has(channel.id);

    const addBtn = document.createElement("button");
    addBtn.type = "button";
    addBtn.className = "subchannel-add-btn";
    addBtn.title = "Add subchannel";
    addBtn.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" width="13" height="13"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>`;
    addBtn.addEventListener("click", e => {
      e.stopPropagation();
      expandedChannels.add(channel.id);
      showSubchannelInput(channel.id, wrap);
    });

    // Order: [handle] [pill] [chevron?] [+]
    row.appendChild(btn);
    if (hasSubs) {
      const chevronBtn = document.createElement("button");
      chevronBtn.type = "button";
      chevronBtn.className = "subchannel-chevron-btn" + (isCollapsed ? " collapsed" : "");
      chevronBtn.title = isCollapsed ? "Expand subchannels" : "Collapse subchannels";
      chevronBtn.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" width="12" height="12"><polyline points="6 9 12 15 18 9"/></svg>`;
      chevronBtn.addEventListener("click", e => {
        e.stopPropagation();
        if (expandedChannels.has(channel.id)) expandedChannels.delete(channel.id);
        else expandedChannels.add(channel.id);
        renderChannelList();
      });
      row.appendChild(chevronBtn);
    }
    row.appendChild(addBtn);
    wrap.appendChild(row);

    // ── Subchannels ──
    if (hasSubs && !isCollapsed) {
      const subList = document.createElement("div");
      subList.className = "subchannel-list";
      channel.subchannels.forEach(sub => {
        const subWrap = document.createElement("div");
        subWrap.className = "subchannel-item-wrap";
        subWrap.draggable = true;

        // ── Subchannel drag ──
        subWrap.addEventListener("dragstart", e => {
          e.stopPropagation();
          dragState = { type: "sub", id: sub.id, parentId: channel.id };
          e.dataTransfer.effectAllowed = "move";
          setTimeout(() => subWrap.classList.add("dragging"), 0);
        });
        subWrap.addEventListener("dragend", e => {
          e.stopPropagation();
          subWrap.classList.remove("dragging");
          dragState = null;
          clearDropIndicators(".subchannel-item-wrap");
        });
        subWrap.addEventListener("dragover", e => {
          if (!dragState || dragState.type !== "sub" || dragState.parentId !== channel.id) return;
          e.preventDefault();
          e.stopPropagation();
          e.dataTransfer.dropEffect = "move";
          clearDropIndicators(".subchannel-item-wrap");
          const rect = subWrap.getBoundingClientRect();
          subWrap.classList.add(e.clientY < rect.top + rect.height / 2 ? "drag-over-top" : "drag-over-bottom");
        });
        subWrap.addEventListener("dragleave", e => {
          if (!subWrap.contains(e.relatedTarget)) subWrap.classList.remove("drag-over-top", "drag-over-bottom");
        });
        subWrap.addEventListener("drop", e => {
          e.preventDefault();
          e.stopPropagation();
          if (!dragState || dragState.type !== "sub" || dragState.parentId !== channel.id || dragState.id === sub.id) return;
          const subs = channel.subchannels;
          const fromIdx = subs.findIndex(s => s.id === dragState.id);
          if (fromIdx === -1) return;
          const [moved] = subs.splice(fromIdx, 1);
          let insertAt = subs.findIndex(s => s.id === sub.id);
          if (insertAt === -1) { subs.push(moved); }
          else {
            const rect = subWrap.getBoundingClientRect();
            if (e.clientY >= rect.top + rect.height / 2) insertAt++;
            subs.splice(insertAt, 0, moved);
          }
          saveState();
          renderChannelList();
        });

        subWrap.appendChild(makeDragHandle());

        const subBtn = document.createElement("button");
        subBtn.type = "button";
        subBtn.className = "channel-pill subchannel-pill" + (sub.id === state.selectedChannelId ? " active" : "");
        subBtn.innerHTML = `<span class="subchannel-prefix">⤷</span><span>${sub.name || "Untitled"}</span>`;
        subBtn.addEventListener("click", () => {
          state.selectedChannelId = sub.id;
          fillForm(sub);
          renderChannelList();
          openSubtab("content");
          _refreshYtPanelsForChannel();
        });
        subWrap.appendChild(subBtn);
        subList.appendChild(subWrap);
      });
      wrap.appendChild(subList);
    }

    el.channelList.appendChild(wrap);
  });
}

function showSubchannelInput(parentId, wrap) {
  document.querySelectorAll(".subchannel-inline-row").forEach(el2 => el2.remove());
  const row = document.createElement("div");
  row.className = "subchannel-inline-row";
  const input = document.createElement("input");
  input.type = "text";
  input.placeholder = "Subchannel name…";
  input.className = "subchannel-name-input";
  const okBtn = document.createElement("button");
  okBtn.type = "button";
  okBtn.className = "subchannel-ok-btn";
  okBtn.textContent = "✓";
  const commit = () => {
    const name = input.value.trim();
    if (name) addSubchannel(parentId, name);
    else renderChannelList();
  };
  okBtn.addEventListener("click", commit);
  input.addEventListener("keydown", e => {
    if (e.key === "Enter") { e.preventDefault(); commit(); }
    if (e.key === "Escape") renderChannelList();
  });
  input.addEventListener("blur", () => { setTimeout(() => { if (!okBtn.matches(":focus")) renderChannelList(); }, 120); });
  row.appendChild(input);
  row.appendChild(okBtn);
  wrap.appendChild(row);
  input.focus();
}

function addSubchannel(parentId, name) {
  const parent = state.channels.find(c => c.id === parentId);
  if (!parent) return;
  if (!parent.subchannels) parent.subchannels = [];
  const sub = emptyChannel(name, parentId);
  parent.subchannels.push(sub);
  state.selectedChannelId = sub.id;
  fillForm(sub);
  saveState();
  renderChannelList();
  openSubtab("content");
}

// ── Channel list ──────────────────────────────────────────────────────────────

function addChannelFromInput() {
  const name = el.newChannelName.value.trim();
  if (!name) return;
  const channel = emptyChannel(name);
  state.channels.unshift(channel);
  state.selectedChannelId = channel.id;
  el.newChannelName.value = "";
  fillForm(channel);
  saveState();
  renderChannelList();
  renderMetrics();
}

function deleteSelectedChannel() {
  const ch = getSelectedChannel();
  if (!ch) return;
  const modal = document.getElementById("deleteConfirmModal");
  document.getElementById("deleteConfirmName").textContent = `"${ch.name}"`;
  modal.classList.add("open");

  const doDelete = () => {
    modal.classList.remove("open");
    if (ch.parentId) {
      // Delete subchannel — remove from parent's subchannels
      const parent = state.channels.find(c => c.id === ch.parentId);
      if (parent) parent.subchannels = parent.subchannels.filter(s => s.id !== ch.id);
      state.selectedChannelId = ch.parentId;
    } else {
      // Delete main channel and all its subchannels
      state.channels = state.channels.filter(c => c.id !== ch.id);
      state.selectedChannelId = state.channels[0]?.id || null;
    }
    fillForm(getSelectedChannel());
    saveState();
    renderChannelList();
    renderMetrics();
    cleanup();
  };
  const cancel = () => { modal.classList.remove("open"); cleanup(); };
  const cleanup = () => {
    document.getElementById("deleteConfirmOk").removeEventListener("click", doDelete);
    document.getElementById("deleteConfirmCancel").removeEventListener("click", cancel);
    document.getElementById("deleteConfirmClose").removeEventListener("click", cancel);
    modal.removeEventListener("click", backdropClose);
  };
  const backdropClose = e => { if (e.target === modal) cancel(); };

  document.getElementById("deleteConfirmOk").addEventListener("click", doDelete);
  document.getElementById("deleteConfirmCancel").addEventListener("click", cancel);
  document.getElementById("deleteConfirmClose").addEventListener("click", cancel);
  modal.addEventListener("click", backdropClose);
}

// ── Modal ─────────────────────────────────────────────────────────────────────
function openDialog(type) {
  const cfg = ACCOUNT_DIALOGS[type];
  if (!cfg) return;
  state.openDialogType = type;
  el.modalTitle.textContent = cfg.title;

  const channel = getSelectedChannel();
  const saved = channel?.accountData?.[type] || {};

  el.modalBody.innerHTML = cfg.fields.map(f => {
    const tag = f.type === "textarea" ? "textarea" : "input";
    const attrs = tag === "textarea"
      ? `rows="3"`
      : `type="${f.type}"`;
    const val = saved[f.id] ? `value="${String(saved[f.id]).replace(/"/g,'&quot;')}"` : "";
    const phAttr = `placeholder="${f.ph.replace(/"/g,'&quot;')}"`;
    const inner = tag === "textarea"
      ? `<textarea id="md-${f.id}" class="modal-input" ${attrs} ${phAttr}>${saved[f.id] || ""}</textarea>`
      : `<input id="md-${f.id}" class="modal-input" ${attrs} ${phAttr} ${val} />`;
    return `<div class="modal-field">
      <label class="modal-label" for="md-${f.id}">${f.label}</label>
      ${inner}
    </div>`;
  }).join("");

  el.modal.classList.add("open");
  el.modalSave.style.display = ""; // ensure Save visible for account dialogs
}

function closeDialog() {
  el.modal.classList.remove("open");
  state.openDialogType = null;
}

function saveDialog() {
  if (state.openDialogType === "__mkt_tag__")      { saveMktTagModal();      return; }
  if (state.openDialogType === "__mkt_schedule__") { saveMktScheduleModal(); return; }
  if (state.openDialogType?.startsWith("__upload__")) { saveUploadCard(); return; }
  const type = state.openDialogType;
  const cfg = ACCOUNT_DIALOGS[type];
  if (!cfg) return;

  const channel = getSelectedChannel();
  if (!channel) { closeDialog(); return; }
  if (!channel.accountData) channel.accountData = emptyAccountData();

  const data = {};
  cfg.fields.forEach(f => {
    const inp = document.getElementById(`md-${f.id}`);
    if (inp) data[f.id] = inp.value.trim();
  });
  channel.accountData[type] = data;

  saveState();
  updateSummaries(channel);
  closeDialog();
}

// ── Inline edit (name + niche) ────────────────────────────────────────────────
function setupInlineEdit() {
  // Channel name
  el.vaultTitle.addEventListener("click", () => {
    const ch = getSelectedChannel();
    if (!ch) return;
    el.channelNameInline.value = ch.name || "";
    el.vaultTitle.style.display = "none";
    el.channelNameInline.style.display = "block";
    el.channelNameInline.focus();
  });

  function commitName() {
    const ch = getSelectedChannel();
    const newName = el.channelNameInline.value.trim();
    if (ch && newName) {
      ch.name = newName;
      el.vaultTitle.textContent = newName;
      saveState();
      renderChannelList();
    }
    el.channelNameInline.style.display = "none";
    el.vaultTitle.style.display = "";
  }

  el.channelNameInline.addEventListener("keydown", e => {
    if (e.key === "Enter") { e.preventDefault(); commitName(); }
    if (e.key === "Escape") { el.channelNameInline.style.display = "none"; el.vaultTitle.style.display = ""; }
  });
  el.channelNameInline.addEventListener("blur", commitName);

  // Niche
  el.nicheDisplay.addEventListener("click", () => {
    const ch = getSelectedChannel();
    if (!ch) return;
    el.channelNicheInline.value = ch.niche || "";
    el.nicheDisplay.style.display = "none";
    el.channelNicheInline.style.display = "block";
    el.channelNicheInline.focus();
  });

  function commitNiche() {
    const ch = getSelectedChannel();
    const newNiche = el.channelNicheInline.value.trim();
    if (ch) {
      ch.niche = newNiche;
      el.nicheDisplay.textContent = newNiche || "No niche set — click to add";
      saveState();
    }
    el.channelNicheInline.style.display = "none";
    el.nicheDisplay.style.display = "";
  }

  el.channelNicheInline.addEventListener("keydown", e => {
    if (e.key === "Enter") { e.preventDefault(); commitNiche(); }
    if (e.key === "Escape") { el.channelNicheInline.style.display = "none"; el.nicheDisplay.style.display = ""; }
  });
  el.channelNicheInline.addEventListener("blur", commitNiche);
}

// ── Vault clickable rows ──────────────────────────────────────────────────────
function setupVaultRows() {
  document.querySelectorAll(".vault-row--clickable").forEach(row => {
    row.addEventListener("click", () => {
      if (!getSelectedChannel()) return;
      openDialog(row.dataset.account);
    });
  });
}

// ── Metrics ───────────────────────────────────────────────────────────────────
// Real numbers come from the ONE authenticated YouTube account — the same
// /api/youtube/channel-videos feed the Content tab uses — and are shown only on
// the Creator Nexus channel that matches it (_channelMatchesAuthedYT). Columns
// the YouTube Data API cannot provide (watch time, retention, impressions, CTR,
// shares, earnings…) need YouTube Analytics access and stay "—".
let _metricsYtError = null;

function _escAttr(s) {
  return _esc(s).replace(/"/g, "&quot;");
}

function _metricsRatio(r) {
  return r == null ? "—" : `${+(r * 100).toFixed(1)}%`;
}

// Sums + ratios over a list of feed videos (one video for a per-video row).
function _ytStats(videos) {
  const sum = k => videos.reduce((n, v) => n + (v[k] || 0), 0);
  const views = sum("views"), likes = sum("likes"), comments = sum("comments"), dislikes = sum("dislikes");
  return {
    views, likes, comments,
    likeRatio:  likes + dislikes ? likes / (likes + dislikes) : null,
    engagement: views ? (likes + comments) / views : null,
  };
}

// Uploads per week from the first upload until today, so a channel that
// stopped uploading shows its rate falling instead of its burst rate.
function _uploadFreqCell(videos) {
  const times = videos.map(v => new Date(v.publishedAt).getTime()).filter(t => !isNaN(t));
  if (!times.length) return "<td>—</td>";
  const first = Math.min(...times), last = Math.max(...times);
  const weeks = Math.max(1, (Date.now() - first) / (7 * 864e5));
  const tip = `${times.length} uploads since ${_fmtDate(first)} · last ${_fmtDate(last)}`;
  return `<td title="${_escAttr(tip)}">${+(times.length / weeks).toFixed(1)}/wk</td>`;
}

function _ytLink(v) {
  return `<a class="metrics-clip" href="https://www.youtube.com/watch?v=${v.id}" target="_blank" rel="noopener" title="${_escAttr(v.title)}">${_esc(v.title)}</a>`;
}

function renderMetrics() {
  if (el.panels.metrics.classList.contains("active") && !_ytVideosCache && !_metricsYtError) {
    _fetchYtVideos(err => { _metricsYtError = err; renderMetrics(); });
  }
  const ytCh = _ytVideosCache ? state.channels.find(_channelMatchesAuthedYT) : null;
  const yt   = ytCh ? _ytStats(_ytVideosCache) : null;

  const subs = yt && !_ytAuthedChannel.subscribersHidden && _ytAuthedChannel.subscribers != null
    ? _fmtNum(_ytAuthedChannel.subscribers) : "—";

  el.sumChannels.textContent    = String(state.channels.length);
  el.sumSubscribers.textContent = subs;
  el.sumViews.textContent       = yt ? _fmtNum(yt.views) : "—";
  el.sumEngagement.textContent  = yt ? _metricsRatio(yt.engagement) : "—";

  _renderVideoMetrics(ytCh);
  el.metricsTableBody.innerHTML = "";

  if (state.channels.length === 0) {
    const row = document.createElement("tr");
    row.innerHTML = '<td colspan="22">No channels yet.</td>';
    el.metricsTableBody.appendChild(row);
    return;
  }

  const viewsOf = ch => (ch === ytCh ? yt.views : -1);
  [...state.channels].sort((a, b) => viewsOf(b) - viewsOf(a)).forEach((ch, i) => {
    const row = document.createElement("tr");
    const head = `<td>${i + 1}</td><td>${_esc(ch.name || "Untitled")}</td><td>${_esc(ch.niche || "—")}</td>`;
    if (ch !== ytCh) {
      row.innerHTML = head + "<td>—</td>".repeat(19);
    } else {
      const videos = _ytVideosCache;
      const pub    = videos.filter(v => v.privacy === "public").length;
      const other  = videos.length - pub;
      const top    = videos.reduce((a, v) => (!a || v.views > a.views ? v : a), null);
      row.innerHTML = head + `
        <td>${subs}</td>
        <td>—</td>
        <td>${pub}${other ? ` <span class="metrics-muted">+${other} not public</span>` : ""}</td>
        ${_uploadFreqCell(videos)}
        <td>${_fmtNum(yt.views)}</td>
        <td>—</td><td>—</td><td>—</td><td>—</td><td>—</td>
        <td>${_metricsRatio(yt.engagement)}</td>
        <td>${_fmtNum(yt.likes)}</td>
        <td>${_fmtNum(yt.comments)}</td>
        <td>—</td>
        <td>${_metricsRatio(yt.likeRatio)}</td>
        <td>—</td><td>—</td><td>—</td>
        <td>${top ? `${_ytLink(top)} <span class="metrics-muted">${_fmtNum(top.views)} views</span>` : "—"}</td>
      `;
    }
    el.metricsTableBody.appendChild(row);
  });
}

function _renderVideoMetrics(ytCh) {
  const body  = el.videoMetricsTableBody;
  const empty = msg => { body.innerHTML = `<tr><td colspan="23" class="metrics-empty">${msg}</td></tr>`; };
  if (_metricsYtError) return empty(`YouTube data unavailable — ${_esc(_metricsYtError.message)}`);
  if (!_ytVideosCache) return empty(el.panels.metrics.classList.contains("active")
    ? "Loading YouTube data…" : "No video data yet — connect platform APIs to populate.");
  if (!ytCh || !_ytVideosCache.length) return empty("No video data yet — connect platform APIs to populate.");

  body.innerHTML = [..._ytVideosCache]
    .sort((a, b) => b.views - a.views || new Date(b.publishedAt) - new Date(a.publishedAt))
    .map(v => {
      const s = _ytStats([v]);
      const privacy = v.privacy !== "public" ? ` <span class="metrics-muted">${_esc(v.privacy)}</span>` : "";
      return `<tr>
        <td class="col-pin">${_ytLink(v)}</td>
        <td>${_esc(ytCh.name || "Untitled")}</td>
        <td>YouTube</td>
        <td>${_fmtDate(v.publishedAt)}${privacy}</td>
        <td>${_fmtNum(v.views)}</td>
        ${"<td>—</td>".repeat(6)}
        <td>${_fmtNum(v.likes)}</td>
        <td>${_metricsRatio(s.likeRatio)}</td>
        <td>${_fmtNum(v.comments)}</td>
        ${"<td>—</td>".repeat(9)}
      </tr>`;
    }).join("");
}

// ── Subtabs ───────────────────────────────────────────────────────────────────
// ── YouTube Content & Scheduled Panels ───────────────────────────────────────
let _ytVideosCache   = null; // shared cache: array of video objects
let _ytCacheLoading  = false;
let _ytCacheCallbacks = [];
let _ytAuthedChannel = null; // {title, id, subscribers} of the ONE authenticated YouTube account (token.pickle)

function _fmtNum(n) {
  if (n >= 1e6) return (n / 1e6).toFixed(1) + "M";
  if (n >= 1e3) return (n / 1e3).toFixed(1) + "K";
  return String(n);
}

function _fmtDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function _fmtDateTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" })
    + " " + d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

function _countdown(iso) {
  if (!iso) return "";
  const ms = new Date(iso) - Date.now();
  if (ms <= 0) return "publishing soon";
  const h = Math.floor(ms / 3600000);
  if (h < 24) return `in ${h}h`;
  return `in ${Math.floor(h / 24)}d`;
}

function _esc(s) {
  return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
}

// Fetch once, deliver to all waiters via callback queue
function _fetchYtVideos(cb) {
  if (_ytVideosCache) { cb(null, _ytVideosCache); return; }
  _ytCacheCallbacks.push(cb);
  if (_ytCacheLoading) return;
  _ytCacheLoading = true;
  fetch(YT_VIDEOS_URL)
    .then(r => r.json())
    .then(data => {
      if (!data.success) throw new Error(data.error || "API error");
      _ytVideosCache = data.videos || [];
      // The endpoint serves the ONE authenticated account (token.pickle). Remember
      // which channel that is so we only show its uploads under the matching
      // Creator Nexus channel — not under every channel.
      _ytAuthedChannel = { title: data.channel || "", id: data.channelId || "",
                           subscribers: data.subscribers, subscribersHidden: !!data.subscribersHidden };
      _ytCacheLoading = false;
      _ytCacheCallbacks.forEach(fn => fn(null, _ytVideosCache));
      _ytCacheCallbacks = [];
    })
    .catch(err => {
      _ytCacheLoading = false;
      _ytCacheCallbacks.forEach(fn => fn(err, null));
      _ytCacheCallbacks = [];
    });
}

function _renderYtVideoCard(v) {
  const bc = { public: "yt-badge-public", private: "yt-badge-private", unlisted: "yt-badge-unlisted" }[v.privacy] || "yt-badge-private";
  const thumb = v.thumbnail
    ? `<img class="yt-vid-thumb" src="${v.thumbnail}" alt="" loading="lazy">`
    : `<div class="yt-vid-thumb" style="background:#0b1422"></div>`;
  return `<a class="yt-vid-card" href="https://www.youtube.com/watch?v=${v.id}" target="_blank" rel="noopener">
  ${thumb}
  <div class="yt-vid-body">
    <div class="yt-vid-title">${_esc(v.title)}</div>
    <div class="yt-vid-stats">
      <span class="yt-vid-stat">👁 ${_fmtNum(v.views)}</span>
      <span class="yt-vid-stat">👍 ${_fmtNum(v.likes)}</span>
      <span class="yt-vid-stat">💬 ${_fmtNum(v.comments)}</span>
    </div>
    <div style="display:flex;justify-content:space-between;align-items:center;">
      <span class="yt-vid-badge ${bc}">${v.privacy}</span>
      <span style="font-size:0.62rem;color:#7a9cbf;">${_fmtDate(v.publishedAt)}</span>
    </div>
  </div>
</a>`;
}

function _renderYtSchedCard(v) {
  const thumb = v.thumbnail
    ? `<img class="yt-vid-thumb" src="${v.thumbnail}" alt="" loading="lazy">`
    : `<div class="yt-vid-thumb" style="background:#0b1422"></div>`;
  const dateRow = v.scheduledPublishAt
    ? `📅 ${_fmtDateTime(v.scheduledPublishAt)} <span class="yt-sched-countdown">${_countdown(v.scheduledPublishAt)}</span>`
    : `🔒 Private · uploaded ${_fmtDate(v.publishedAt)}`;
  return `<a class="yt-sched-card" href="https://www.youtube.com/watch?v=${v.id}" target="_blank" rel="noopener">
  ${thumb}
  <div class="yt-sched-date">${dateRow}</div>
  <div class="yt-vid-body">
    <div class="yt-vid-title">${_esc(v.title)}</div>
    <div class="yt-vid-stats">
      <span class="yt-vid-stat">👁 ${_fmtNum(v.views)}</span>
      <span class="yt-vid-stat">👍 ${_fmtNum(v.likes)}</span>
      <span class="yt-vid-stat">💬 ${_fmtNum(v.comments)}</span>
    </div>
  </div>
</a>`;
}

// True only when a Creator Nexus channel IS the one authenticated YouTube
// account. There is a single token.pickle (ZygomaticDocumentaries), so its
// uploads and stats must appear ONLY under the matching channel — otherwise
// every channel shows the same videos. Matches on the channel's configured
// YouTube URL/handle, its name, or the raw channel ID.
function _selectedChannelMatchesAuthedYT() {
  return _channelMatchesAuthedYT(getSelectedChannel());
}

function _channelMatchesAuthedYT(ch) {
  if (!_ytAuthedChannel || (!_ytAuthedChannel.title && !_ytAuthedChannel.id)) return false;
  if (!ch) return false;
  const yt = (ch.accountData && ch.accountData.youtube) || {};
  const norm = s => String(s || "").toLowerCase().replace(/[^a-z0-9]/g, "");
  const hay = norm([yt.channelUrl, yt.username, ch.name].filter(Boolean).join(" "));
  if (!hay) return false;
  const title = norm(_ytAuthedChannel.title);
  const id    = norm(_ytAuthedChannel.id);
  if (id && hay.includes(id)) return true;       // handle stores the UC… id
  if (title && hay.includes(title)) return true;  // handle/name contains the channel title
  return false;
}

// A single empty placeholder card for channels with no videos (instead of a
// text notification). Non-interactive, greyed-out, matches the kanban layout.
function _ytBlankCardHtml() {
  return `<div class="yt-vid-grid"><div class="yt-vid-card yt-vid-card-blank" style="pointer-events:none;opacity:0.4;">
    <div class="yt-vid-thumb" style="background:#0b1422"></div>
    <div class="yt-vid-body">
      <div class="yt-vid-title">&nbsp;</div>
      <div class="yt-vid-stats"><span class="yt-vid-stat">&nbsp;</span></div>
    </div>
  </div></div>`;
}

// Called on channel switch: clear any previously-rendered YT grids so the
// channel-match guard re-runs for the newly-selected channel. Uses the cached
// video list (no re-fetch) and only re-renders the currently-visible panel.
function _refreshYtPanelsForChannel() {
  const pubPanel   = document.getElementById("platform-youtube");
  const pubKanban  = pubPanel && pubPanel.querySelector(".content-kanban");
  if (pubKanban) pubKanban.innerHTML = "";
  const schedKanban = document.querySelector("#subtab-scheduled .content-kanban");
  if (schedKanban) schedKanban.innerHTML = "";
  const contentActive = document.getElementById("subtab-content")?.classList.contains("active");
  if (contentActive && pubPanel && pubPanel.classList.contains("active")) _loadYouTubePanel();
  if (document.getElementById("subtab-scheduled")?.classList.contains("active")) _loadYouTubeScheduled();
}

// Content tab: only public / unlisted (actually uploaded and visible)
function _loadYouTubePanel(force) {
  const panel = document.getElementById("platform-youtube");
  if (!panel) return;
  const kanban = panel.querySelector(".content-kanban");
  if (!kanban) return;
  if (!force && kanban.querySelector(".yt-vid-grid")) return; // already rendered
  if (force) { _ytVideosCache = null; _ytCacheLoading = false; _ytCacheCallbacks = []; }

  kanban.innerHTML = `<div class="yt-vid-loading">Loading videos…</div>`;
  _fetchYtVideos((err, videos) => {
    if (err) { kanban.innerHTML = `<div class="yt-vid-error">⚠ ${err.message}</div>`; return; }
    if (!_selectedChannelMatchesAuthedYT()) { kanban.innerHTML = _ytBlankCardHtml(); return; }
    const pub = videos.filter(v =>
      (v.privacy === "public" || v.privacy === "unlisted") &&
      new Date(v.publishedAt).getFullYear() >= 2025
    );
    if (!pub.length) {
      kanban.innerHTML = _ytBlankCardHtml();
      return;
    }
    kanban.innerHTML = `<div class="yt-vid-grid">${pub.map(_renderYtVideoCard).join("")}</div>`;
  });
}

// Scheduled tab: all private 2025+ videos (uploaded but not yet public)
function _loadYouTubeScheduled(force) {
  const kanban = document.querySelector("#subtab-scheduled .content-kanban");
  if (!kanban) return;
  if (!force && kanban.querySelector(".yt-sched-grid")) return; // already rendered

  kanban.innerHTML = `<div class="yt-vid-loading">Loading scheduled videos…</div>`;
  _fetchYtVideos((err, videos) => {
    if (err) { kanban.innerHTML = `<div class="yt-vid-error">⚠ ${err.message}</div>`; return; }
    if (!_selectedChannelMatchesAuthedYT()) { kanban.innerHTML = _ytBlankCardHtml(); return; }
    const sched = videos.filter(v =>
      v.privacy === "private" &&
      new Date(v.publishedAt).getFullYear() >= 2025
    ).sort((a, b) => new Date(b.publishedAt) - new Date(a.publishedAt));
    if (!sched.length) {
      kanban.innerHTML = _ytBlankCardHtml();
      return;
    }
    kanban.innerHTML = `<div class="yt-sched-grid">${sched.map(_renderYtSchedCard).join("")}</div>`;
  });
}

function renderPlatformTabs(region) {
  const bar = document.getElementById("platformBar");
  const platforms = REGION_PLATFORMS[region] || REGION_PLATFORMS.english;
  bar.innerHTML = platforms.map((p, i) => `
    <button class="platform-tab${i === 0 ? " active" : ""}" data-platform="${p.id}" type="button" title="${p.title}" style="--pc:#${p.color}">
      <img src="https://cdn.simpleicons.org/${p.slug}/${p.color}" alt="${p.title}" width="20" height="20">
    </button>`).join("");

  // hide all panels, show first
  document.querySelectorAll(".platform-panel").forEach(p => p.classList.remove("active"));
  document.getElementById(`platform-${platforms[0].id}`)?.classList.add("active");

  // wire clicks
  bar.querySelectorAll(".platform-tab").forEach(tab => {
    tab.addEventListener("click", () => {
      bar.querySelectorAll(".platform-tab").forEach(t => t.classList.remove("active"));
      document.querySelectorAll(".platform-panel").forEach(p => p.classList.remove("active"));
      tab.classList.add("active");
      document.getElementById(`platform-${tab.dataset.platform}`)?.classList.add("active");
      // load real YouTube videos when YouTube tab becomes active inside Content subtab
      if (tab.dataset.platform === "youtube") {
        const contentPanel = document.getElementById("subtab-content");
        if (contentPanel && contentPanel.classList.contains("active")) _loadYouTubePanel();
      }
    });
  });
}

function setupRegionSelector() {
  const btn  = document.getElementById("regionBtn");
  const menu = document.getElementById("regionMenu");
  const label = document.getElementById("regionLabel");
  if (!btn || !menu) return;

  btn.addEventListener("click", e => { e.stopPropagation(); menu.hidden = !menu.hidden; });

  menu.querySelectorAll(".region-opt").forEach(opt => {
    opt.addEventListener("click", e => {
      e.stopPropagation();
      const region = opt.dataset.region;
      menu.querySelectorAll(".region-opt").forEach(o => o.classList.remove("active"));
      opt.classList.add("active");
      label.textContent = opt.textContent.replace(/^\S+\s/, ""); // strip flag emoji
      menu.hidden = true;
      renderPlatformTabs(region);
    });
  });

  document.addEventListener("click", () => { menu.hidden = true; });
  renderPlatformTabs("english");
}

function openSubtab(id) {
  document.querySelectorAll(".subtab").forEach(t => t.classList.remove("active"));
  document.querySelectorAll(".subtab-panel").forEach(p => p.classList.remove("active"));
  const tab = document.querySelector(`.subtab[data-subtab="${id}"]`);
  const panel = document.getElementById(`subtab-${id}`);
  if (tab) tab.classList.add("active");
  if (panel) panel.classList.add("active");
}

function setupSubtabs() {
  document.querySelectorAll(".subtab").forEach(tab => {
    tab.addEventListener("click", () => {
      const panel = document.getElementById(`subtab-${tab.dataset.subtab}`);
      const isOpen = panel.classList.contains("active");
      document.querySelectorAll(".subtab").forEach(t => t.classList.remove("active"));
      document.querySelectorAll(".subtab-panel").forEach(p => p.classList.remove("active"));
      if (!isOpen) {
        tab.classList.add("active");
        panel.classList.add("active");
        if (tab.dataset.subtab === "content") {
          const ytPanel = document.getElementById("platform-youtube");
          if (ytPanel && ytPanel.classList.contains("active")) _loadYouTubePanel();
        }
        if (tab.dataset.subtab === "scheduled") _loadYouTubeScheduled();
      }
    });
  });
}

// ── Main tabs ─────────────────────────────────────────────────────────────────
function setupTabs() {
  el.tabs.forEach(tab => {
    tab.addEventListener("click", () => {
      const target = tab.dataset.tab;
      el.tabs.forEach(t => t.classList.remove("active"));
      tab.classList.add("active");
      Object.entries(el.panels).forEach(([name, panel]) => {
        panel.classList.toggle("active", name === target);
      });
      if (target === "metrics") { _metricsYtError = null; renderMetrics(); } // re-opening retries a failed fetch
    });
  });
}

// ── Seed demo ─────────────────────────────────────────────────────────────────
function seedDemoIfEmpty() {
  if (state.channels.length > 0) return;
  const ch = emptyChannel("Sample Channel");
  ch.niche = "Creator Operations";
  ch.__demoSeed = true;   // never synced to the server; replaced by any real restore
  state.channels = [ch];
  state.selectedChannelId = ch.id;
}

// ── Comments dialog ───────────────────────────────────────────────────────────
const AVATAR_COLORS = ["#6dc6ff","#7affc1","#ff9f6b","#c97bff","#ffde6b","#ff7bab"];

const MOCK_COMMENTS = [
  { author: "Alex Martens",    text: "This content is genuinely top tier. Keep it up!", likes: 142, time: "2 days ago" },
  { author: "NightOwl_Dev",    text: "Honestly one of the best breakdowns I've seen on this topic.", likes: 87, time: "3 days ago" },
  { author: "Soph.Creates",    text: "The editing on this one was insane 🔥", likes: 63, time: "3 days ago" },
  { author: "MarcusTalks",     text: "Just subbed. Can't believe I found this channel this late.", likes: 55, time: "4 days ago" },
  { author: "quietviewer99",   text: "I've been watching for months and never commented but this one deserved it.", likes: 44, time: "5 days ago" },
  { author: "TrendWatcherYT",  text: "Algorithm finally did something right pushing this to my feed.", likes: 38, time: "5 days ago" },
  { author: "Lena K.",         text: "Timestamp at 3:42 is pure gold. Saved that part.", likes: 29, time: "6 days ago" },
  { author: "d4rkmode_on",     text: "Could you do a follow-up on the second point you made? Would love more depth.", likes: 21, time: "1 week ago" },
];

function openCommentsDialog(videoTitle) {
  el.commentsModalTitle.textContent = `Comments — ${videoTitle}`;
  el.commentsModalBody.innerHTML = MOCK_COMMENTS.map((c, i) => {
    const initials = c.author.split(" ").map(w => w[0]).join("").slice(0, 2).toUpperCase();
    const color = AVATAR_COLORS[i % AVATAR_COLORS.length];
    return `
      <div class="comment-item">
        <div class="comment-avatar" style="background:${color}">${initials}</div>
        <div class="comment-body">
          <div class="comment-author">${c.author}</div>
          <div class="comment-text">${c.text}</div>
          <div class="comment-meta">
            <span>👍 ${c.likes}</span>
            <span>${c.time}</span>
          </div>
        </div>
      </div>`;
  }).join("");
  el.commentsModal.classList.add("open");
}

function closeCommentsDialog() {
  el.commentsModal.classList.remove("open");
}

function closeSettings() {
  el.settingsMenu.classList.remove("open");
  el.settingsBtn.classList.remove("open");
}

function setupSchedPlatformPickers() {
  document.querySelectorAll(".sched-platform-picker").forEach(picker => {
    const icon = picker.querySelector(".sched-platform-icon");
    const menu = picker.querySelector(".sched-platform-menu");
    picker.addEventListener("click", e => {
      e.stopPropagation();
      menu.hidden = !menu.hidden;
    });
    menu.querySelectorAll(".sched-platform-opt").forEach(opt => {
      opt.addEventListener("click", e => {
        e.stopPropagation();
        const p = opt.dataset.p;
        const color = opt.dataset.color;
        icon.src = `https://cdn.simpleicons.org/${p}/${color}`;
        icon.alt = p;
        icon.dataset.platform = p;
        menu.hidden = true;
      });
    });
  });
  document.addEventListener("click", () => {
    document.querySelectorAll(".sched-platform-menu").forEach(m => m.hidden = true);
  });
}

// ── Upload Pipeline ───────────────────────────────────────────────────────────
const UPLOAD_KEY = "creator_nexus_upload_v1";

const PLATFORM_AIR_SLOTS = {
  youtube:   ["08:00", "12:00", "17:00"],
  tiktok:    ["07:00", "12:00", "19:00"],
  instagram: ["08:00", "11:00", "17:00"],
  facebook:  ["09:00", "13:00", "15:00"],
  x:         ["08:00", "12:00", "16:00"],
  kick:      ["18:00", "20:00", "22:00"],
  telegram:  ["09:00", "13:00", "18:00"],
  vk:        ["09:00", "13:00", "19:00"],
  bilibili:  ["12:00", "18:00", "20:00"],
  sinaweibo: ["08:00", "12:00", "19:00"],
  wechat:    ["08:00", "12:00", "19:00"],
  douyin:    ["07:00", "12:00", "19:00"],
};

const SCHED_COLS = [
  {
    id: "collecting", stage: 1,
    label: "Collecting Content", step: "Stage 1 · Step 1",
    fields: [
      { id: "title",  label: "Title",  type: "text",     ph: "Video title" },
      { id: "source", label: "Source", type: "text",     ph: "File path or link" },
      { id: "notes",  label: "Notes",  type: "textarea", ph: "Notes..." },
    ],
  },
  {
    id: "description", stage: 1,
    label: "Description Creator", step: "Stage 1 · Step 2",
    fields: [
      { id: "title",       label: "Title",       type: "text",     ph: "Video title" },
      { id: "description", label: "Description", type: "textarea", ph: "Write description..." },
      { id: "hashtags",    label: "Hashtags",    type: "text",     ph: "#content #creator" },
    ],
  },
  {
    id: "thumbnail", stage: 1,
    label: "Thumbnail Creator", step: "Stage 1 · Step 3",
    fields: [
      { id: "title",       label: "Title",            type: "text",     ph: "Video title" },
      { id: "thumbStatus", label: "Thumbnail Status", type: "select",   opts: ["Needed", "In Progress", "Done"] },
      { id: "notes",       label: "Design Notes",     type: "textarea", ph: "Design notes..." },
    ],
  },
  {
    id: "uploadtime", stage: 2,
    label: "Upload Date / Time", step: "Stage 2 · Step 1 · 07:00 AMS",
    fields: [
      { id: "title",      label: "Content Title", type: "text", ph: "Video title" },
      { id: "uploadDate", label: "Upload Date",   type: "date", ph: "" },
    ],
  },
  {
    id: "airtime", stage: 2,
    label: "Air Date / Time", step: "Stage 2 · Step 2",
    fields: [
      { id: "title",       label: "Content Title",     type: "text",   ph: "Video title" },
      { id: "platform",    label: "Platform",           type: "select", opts: ["youtube","tiktok","instagram","facebook","x","kick","telegram","vk","bilibili","sinaweibo","wechat","douyin"] },
      { id: "airDate",     label: "Air Date",           type: "date",   ph: "" },
      { id: "slot1",       label: "Slot 1",             type: "time",   ph: "" },
      { id: "slot2",       label: "Slot 2",             type: "time",   ph: "" },
      { id: "slot3",       label: "Slot 3",             type: "time",   ph: "" },
    ],
  },
];

const PIPELINE_LOGIN_PLATFORMS = [
  { id: "facebook",  title: "Facebook",  color: "1877F2", slug: "facebook" },
  { id: "tiktok",    title: "TikTok",    color: "FE2C55", slug: "tiktok" },
  { id: "instagram", title: "Instagram", color: "E4405F", slug: "instagram" },
  { id: "kick",      title: "Kick",      color: "53FC18", slug: "kick" },
];

const PIPELINE_API_PLATFORMS = [
  { id: "youtube",  title: "YouTube",  color: "FF0000", slug: "youtube" },
  { id: "x",        title: "X",        color: "ffffff", slug: "x" },
  { id: "telegram", title: "Telegram", color: "26A5E4", slug: "telegram" },
];

const PIPELINE_STATUSES = ["pending", "in-progress", "done", "failed"];

let uploadState = {
  sched: { collecting: [], description: [], thumbnail: [], uploadtime: [], airtime: [] },
  pipeline: { login: {}, upload: "pending", verify: "pending" },
  pipelineRegion: "english",
};

function loadUploadState() {
  try {
    const raw = localStorage.getItem(UPLOAD_KEY);
    if (raw) {
      const p = JSON.parse(raw);
      uploadState = {
        sched: { ...uploadState.sched, ...(p.sched || {}) },
        pipeline: { login: {}, upload: "pending", verify: "pending", ...(p.pipeline || {}) },
        pipelineRegion: p.pipelineRegion || "english",
      };
    }
  } catch (e) {}
}

function saveUploadState() {
  localStorage.setItem(UPLOAD_KEY, JSON.stringify(uploadState));
  _cnScheduleSync();
}

function esc(str) {
  return String(str).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}

function renderUploadCardHtml(colCfg, card) {
  let body = "";
  if (colCfg.id === "collecting") {
    body = `<div class="upload-card-title">${esc(card.title||"Untitled")}</div>
      ${card.source ? `<div class="upload-card-meta">📁 ${esc(card.source)}</div>` : ""}
      ${card.notes  ? `<div class="upload-card-notes">${esc(card.notes)}</div>` : ""}`;
  } else if (colCfg.id === "description") {
    const d = card.description || "";
    body = `<div class="upload-card-title">${esc(card.title||"Untitled")}</div>
      ${d ? `<div class="upload-card-notes">${esc(d.slice(0,80))}${d.length>80?"…":""}</div>` : ""}
      ${card.hashtags ? `<div class="upload-card-hashtags">${esc(card.hashtags)}</div>` : ""}`;
  } else if (colCfg.id === "thumbnail") {
    const st = card.thumbStatus || "Needed";
    const cls = st.toLowerCase().replace(/\s+/g, "-");
    body = `<div class="upload-card-title">${esc(card.title||"Untitled")}</div>
      <span class="upload-status upload-status--${cls}">${st}</span>
      ${card.notes ? `<div class="upload-card-notes">${esc(card.notes)}</div>` : ""}`;
  } else if (colCfg.id === "uploadtime") {
    body = `<div class="upload-card-title">${esc(card.title||"Untitled")}</div>
      <span class="upload-time-badge">⏰ 07:00 AMS</span>
      <div class="upload-card-meta" style="margin-top:5px">📅 ${esc(card.uploadDate||"No date set")}</div>`;
  } else if (colCfg.id === "airtime") {
    const slots = [card.slot1, card.slot2, card.slot3].filter(Boolean);
    const disclosureBadge = `<span class="ai-badge ai-badge--on" title="Altered or synthetic content label automatically applied">🛡 AI Disclosed</span>`;
    body = `<div class="upload-card-title">${esc(card.title||"Untitled")}</div>
      <div class="upload-card-meta">
        ${card.platform ? `<img src="https://cdn.simpleicons.org/${card.platform}/ffffff" width="12" height="12" alt="${card.platform}" style="vertical-align:middle" />` : ""}
        <span>${esc(card.platform||"—")}</span>
        <span style="margin-left:auto">📅 ${esc(card.airDate||"—")}</span>
      </div>
      <div class="upload-slot-row">${slots.map(s=>`<span class="upload-slot-chip">🕐 ${esc(s)}</span>`).join("")}</div>
      ${disclosureBadge}`;
  }
  return `<div class="upload-card-item" data-ucard="${card.id}" data-ucol="${colCfg.id}">
    ${body}
    <button class="upload-card-del" data-ucard-del="${card.id}" data-ucol="${colCfg.id}" title="Delete">×</button>
  </div>`;
}

function renderUploadCol(colCfg) {
  const cards = uploadState.sched[colCfg.id] || [];
  const fixedTime = colCfg.id === "uploadtime"
    ? `<div class="upload-col-fixed-time">07:00 AMS</div>` : "";
  return `<div class="upload-col-wrap">
    <div class="upload-col-step-lbl">${colCfg.step}</div>
    <div class="upload-col">
      <div class="upload-col-header">${colCfg.label}</div>
      ${fixedTime}
      <div class="upload-col-cards">${cards.map(c => renderUploadCardHtml(colCfg, c)).join("")}</div>
    </div>
  </div>`;
}

function renderSchedKanban() {
  const wrap = document.getElementById("ustab-sched-wrap");
  if (!wrap) return;
  const s1 = SCHED_COLS.filter(c => c.stage === 1);
  const s2 = SCHED_COLS.filter(c => c.stage === 2);
  wrap.innerHTML = `
    <div class="upload-stage-block">
      <div class="upload-stage-label"><span class="upload-stage-number">Stage 1</span><span class="upload-stage-title">Content Preparation</span></div>
      <div class="upload-kanban upload-kanban--vert">${s1.map(renderUploadCol).join("")}</div>
    </div>
    <div class="upload-stage-block">
      <div class="upload-stage-label"><span class="upload-stage-number">Stage 2</span><span class="upload-stage-title">Scheduling</span></div>
      <div class="upload-kanban upload-kanban--vert">${s2.map(renderUploadCol).join("")}</div>
    </div>`;
  wrap.querySelectorAll("[data-ucard-del]").forEach(btn => {
    btn.addEventListener("click", e => {
      e.stopPropagation();
      const { ucardDel: cid, ucol: col } = btn.dataset;
      uploadState.sched[col] = (uploadState.sched[col]||[]).filter(c => c.id !== cid);
      saveUploadState();
      renderSchedKanban();
    });
  });
}

function statusLabel(s) {
  return { pending:"⚪ Pending", "in-progress":"🟡 In Progress", done:"🟢 Done", failed:"🔴 Failed" }[s] || s;
}

function renderPipelineKanban() {
  const wrap = document.getElementById("ustab-pipe-wrap");
  if (!wrap) return;

  const REGION_FLAGS  = { english:"🇬🇧", spanish:"🇪🇸", french:"🇫🇷", indian:"🇮🇳", chinese:"🇨🇳", russian:"🇷🇺" };
  const REGION_LABELS = { english:"English", spanish:"Spanish", french:"French", indian:"Indian", chinese:"Chinese", russian:"Russian" };
  const region = uploadState.pipelineRegion || "english";
  const regionPlatforms = REGION_PLATFORMS[region] || REGION_PLATFORMS.english;
  const loginPlatforms = regionPlatforms.filter(p => !API_PLATFORM_IDS.has(p.id));

  const loginCards = loginPlatforms.map((p, i) =>
    `<div class="pipe-step-card" data-pipe-login="${p.id}">
      <span class="pipe-step-num">Step ${i + 1}</span>
      <img src="https://cdn.simpleicons.org/${p.slug}/${p.color}" width="16" height="16" alt="${p.title}" class="pipe-step-icon" />
      <span class="pipe-step-name">${esc(p.title)}</span>
    </div>`
  ).join("");

  const platformList = `<div class="pipe-plat-list">
    ${regionPlatforms.map(p =>
      `<div class="pipe-plat-row">
        <img src="https://cdn.simpleicons.org/${p.slug}/${p.color}" width="13" height="13" alt="${p.title}" />
        <span>${esc(p.title)}</span>
      </div>`
    ).join("")}
  </div>`;

  wrap.innerHTML = `
    <div class="pipe-layout">
      <div class="pipe-stage">
        <div class="pipe-stage-hdr"><span class="pipe-stage-num">Stage 1</span><span class="pipe-stage-name">Login</span></div>
        ${loginCards}
      </div>
      <div class="pipe-stage">
        <div class="pipe-stage-hdr"><span class="pipe-stage-num">Stage 2</span><span class="pipe-stage-name">Upload</span></div>
        <div class="pipe-step-card" data-pipe-exec="collect">
          <span class="pipe-step-num">Step 1</span>
          <span class="pipe-step-name">Collecting Content</span>
        </div>
        <div class="pipe-step-card pipe-step-card--disclosure pipe-step-card--auto">
          <span class="pipe-step-num">Step 2</span>
          <span class="pipe-step-name">
            <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" width="12" height="12" style="vertical-align:-1px;margin-right:4px"><path d="M8 1L2 4v4c0 3.3 2.6 6.4 6 7 3.4-.6 6-3.7 6-7V4L8 1z"/></svg>AI Disclosure Labels
          </span>
          <span class="pipe-step-auto-badge">🟢 Auto</span>
          <span class="pipe-step-sub">Altered or synthetic content — enforced on every upload</span>
        </div>
        <div class="pipe-step-card" data-pipe-exec="upload">
          <span class="pipe-step-num">Step 3</span>
          <span class="pipe-step-name">Upload All Content</span>
        </div>
        ${platformList}
        <div class="pipe-step-card" data-pipe-exec="verify">
          <span class="pipe-step-num">Step 4</span>
          <span class="pipe-step-name">Verification</span>
        </div>
      </div>
    </div>`;

  // Update tab-bar region dropdown label to reflect current region
  const tabBarLabel = document.getElementById("uploadRegionLabel");
  if (tabBarLabel) tabBarLabel.textContent = `${REGION_FLAGS[region]} ${REGION_LABELS[region]}`;
  const tabBarMenu = document.getElementById("uploadRegionMenu");
  if (tabBarMenu) {
    tabBarMenu.querySelectorAll(".region-opt").forEach(o =>
      o.classList.toggle("active", o.dataset.pipeRegion === region)
    );
  }

  wrap.querySelectorAll("[data-pipe-login]").forEach(card => {
    card.addEventListener("click", () => {
      const pid = card.dataset.pipeLogin;
      const cur = uploadState.pipeline.login[pid] || "pending";
      uploadState.pipeline.login[pid] = PIPELINE_STATUSES[(PIPELINE_STATUSES.indexOf(cur)+1) % PIPELINE_STATUSES.length];
      saveUploadState(); renderPipelineKanban();
    });
  });
  wrap.querySelectorAll("[data-pipe-exec]").forEach(card => {
    card.addEventListener("click", () => {
      const key = card.dataset.pipeExec;
      const cur = uploadState.pipeline[key] || "pending";
      uploadState.pipeline[key] = PIPELINE_STATUSES[(PIPELINE_STATUSES.indexOf(cur)+1) % PIPELINE_STATUSES.length];
      saveUploadState(); renderPipelineKanban();
    });
  });
}

function startPipelineCountdown() {
  function tick() {
    const el2 = document.getElementById("pipelineCountdown");
    if (!el2) return;
    const now = new Date();
    const amsNow = new Date(now.toLocaleString("en-US", { timeZone: "Europe/Amsterdam" }));
    const target = new Date(amsNow);
    target.setHours(7, 0, 0, 0);
    if (amsNow >= target) target.setDate(target.getDate() + 1);
    const diff = target - amsNow;
    const h = Math.floor(diff / 3600000);
    const m = Math.floor((diff % 3600000) / 60000);
    const s = Math.floor((diff % 60000) / 1000);
    el2.textContent = `${String(h).padStart(2,"0")}:${String(m).padStart(2,"0")}:${String(s).padStart(2,"0")}`;
  }
  tick();
  setInterval(tick, 1000);
}

function openUploadCardDialog(colId) {
  const colCfg = SCHED_COLS.find(c => c.id === colId);
  if (!colCfg) return;
  state.openDialogType = `__upload__${colId}`;
  el.modalTitle.textContent = colCfg.label;
  el.modalBody.innerHTML = colCfg.fields.map(f => {
    let input = "";
    if (f.type === "toggle") {
      input = `<div class="modal-toggle-wrap">
        <label class="ai-toggle-switch">
          <input type="checkbox" id="md-${f.id}" ${f.defaultOn ? "checked" : ""} />
          <span class="ai-toggle-slider"></span>
        </label>
        <div class="ai-toggle-info">
          <span class="ai-toggle-title">Altered or Synthetic Content</span>
          <span class="ai-toggle-desc">Required by YouTube, TikTok &amp; Meta — enables the AI disclosure label. Keep ON for all AI-generated visuals, voice &amp; scripts.</span>
        </div>
      </div>`;
      return `<div class="modal-field modal-field--toggle">${input}</div>`;
    } else if (f.type === "select") {
      input = `<select id="md-${f.id}" class="modal-input" style="color-scheme:dark;background:#0c1624;border:1px solid #2e435f;border-radius:10px;color:var(--text);padding:8px 12px;font-size:0.88rem;width:100%">
        ${f.opts.map(o => `<option value="${o.toLowerCase()}">${o}</option>`).join("")}
      </select>`;
    } else if (f.type === "textarea") {
      input = `<textarea id="md-${f.id}" class="modal-input" rows="3" placeholder="${esc(f.ph)}"></textarea>`;
    } else {
      input = `<input id="md-${f.id}" class="modal-input" type="${f.type}" placeholder="${esc(f.ph)}" />`;
    }
    return `<div class="modal-field"><label class="modal-label" for="md-${f.id}">${f.label}</label>${input}</div>`;
  }).join("");

  if (colId === "uploadtime") {
    const dateField = document.getElementById("md-uploadDate")?.closest(".modal-field");
    if (dateField) {
      const badge = document.createElement("div");
      badge.style.marginBottom = "6px";
      badge.innerHTML = `<span class="upload-time-badge">⏰ Fixed upload time: 07:00 AMS</span>`;
      dateField.insertBefore(badge, dateField.querySelector("input"));
    }
  }

  if (colId === "airtime") {
    const plat = document.getElementById("md-platform");
    const [s1, s2, s3] = ["md-slot1","md-slot2","md-slot3"].map(id => document.getElementById(id));
    function fillSlots() {
      const p = plat?.value || "default";
      const slots = PLATFORM_AIR_SLOTS[p] || ["08:00","13:00","18:00"];
      if (s1) s1.value = slots[0];
      if (s2) s2.value = slots[1];
      if (s3) s3.value = slots[2];
    }
    plat?.addEventListener("change", fillSlots);
    fillSlots();
    const airDateField = document.getElementById("md-airDate")?.closest(".modal-field");
    if (airDateField) {
      const note = document.createElement("div");
      note.className = "telemetry-note";
      note.textContent = "Min. 24h after upload date";
      airDateField.appendChild(note);
      const tomorrow = new Date();
      tomorrow.setDate(tomorrow.getDate() + 1);
      document.getElementById("md-airDate").min = tomorrow.toISOString().split("T")[0];
    }
  }

  el.modal.classList.add("open");
  el.modalSave.style.display = "";
}

function saveUploadCard() {
  const colId = (state.openDialogType || "").replace("__upload__", "");
  const colCfg = SCHED_COLS.find(c => c.id === colId);
  if (!colCfg) return;
  const card = { id: uid() };
  colCfg.fields.forEach(f => {
    const inp = document.getElementById(`md-${f.id}`);
    if (!inp) return;
    card[f.id] = inp.type === "checkbox" ? inp.checked : inp.value.trim();
  });
  // AI disclosure is mandatory for all content — enforce automatically
  if (colId === "airtime") card.aiDisclosure = true;
  if (!uploadState.sched[colId]) uploadState.sched[colId] = [];
  uploadState.sched[colId].push(card);
  saveUploadState();
  renderSchedKanban();
  closeDialog();
}

function setupUploadSubtabs() {
  document.querySelectorAll(".upload-stab").forEach(tab => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".upload-stab").forEach(t => t.classList.remove("active"));
      document.querySelectorAll(".upload-stab-panel").forEach(p => p.classList.remove("active"));
      tab.classList.add("active");
      document.getElementById(`ustab-${tab.dataset.ustab}`)?.classList.add("active");
    });
  });

  // Wire tab-bar globe button as pipeline region selector
  const REGION_FLAGS  = { english:"🇬🇧", spanish:"🇪🇸", french:"🇫🇷", indian:"🇮🇳", chinese:"🇨🇳", russian:"🇷🇺" };
  const REGION_LABELS = { english:"English", spanish:"Spanish", french:"French", indian:"Indian", chinese:"Chinese", russian:"Russian" };
  const settingsBtn = document.getElementById("uploadSettingsBtn");
  if (!settingsBtn) return;

  // Build dropdown and insert after the button
  const menuEl = document.createElement("div");
  menuEl.className = "region-menu";
  menuEl.id = "uploadRegionMenu";
  menuEl.hidden = true;
  menuEl.innerHTML = Object.keys(REGION_LABELS).map(r =>
    `<button class="region-opt${r === (uploadState.pipelineRegion||"english") ? " active" : ""}" data-pipe-region="${r}" type="button">${REGION_FLAGS[r]} ${REGION_LABELS[r]}</button>`
  ).join("");
  settingsBtn.parentElement.style.position = "relative";
  settingsBtn.parentElement.appendChild(menuEl);

  // Label span inside button
  const labelSpan = document.createElement("span");
  labelSpan.id = "uploadRegionLabel";
  labelSpan.style.cssText = "font-size:0.72rem;font-weight:600;margin-left:4px";
  const cur = uploadState.pipelineRegion || "english";
  labelSpan.textContent = `${REGION_FLAGS[cur]} ${REGION_LABELS[cur]}`;
  settingsBtn.appendChild(labelSpan);

  settingsBtn.addEventListener("click", e => {
    e.stopPropagation();
    menuEl.hidden = !menuEl.hidden;
  });
  document.addEventListener("click", () => { menuEl.hidden = true; });
  menuEl.querySelectorAll("[data-pipe-region]").forEach(btn => {
    btn.addEventListener("click", e => {
      e.stopPropagation();
      uploadState.pipelineRegion = btn.dataset.pipeRegion;
      saveUploadState();
      renderPipelineKanban();
      menuEl.hidden = true;
    });
  });
}

function initUploadTab() {
  loadUploadState();
  setupUploadSubtabs();
  renderSchedKanban();
  renderPipelineKanban();
  startPipelineCountdown();
}

// ── Marketing Kanban ──────────────────────────────────────────────────────────
const MKT_KEY         = "creator_nexus_mkt_v1";
const MKT_LOG_KEY     = "creator_nexus_mkt_log_v1";
const MKT_MAX_LOG     = 600;
const MKT_BATCH_SLOTS = ["07:00", "13:00", "19:00"];   // upload 1 h before the 08:00/14:00/20:00 air slots
const MKT_SCAN_URL    = `${API_BASE}/api/output/new-videos`;
const MKT_UPLOAD_URL  = `${API_BASE}/api/marketing/upload`;
const MKT_DISMISS_URL = `${API_BASE}/api/marketing/dismiss`;
const YT_VIDEOS_URL   = `${API_BASE}/api/youtube/channel-videos`;
const MKT_SCAN_INTERVAL     = 10000;          // 10 s
const MKT_ARCHIVE_DONE_MS   = 6  * 3600000;  // archive ✓ Done after 6 h
const MKT_ARCHIVE_ERROR_MS  = 48 * 3600000;  // archive ⚠ Error after 48 h

let mktState = {
  folderName: "",
  usedKeys:   [],
  dismissedKeys: [],
  episodes: { production: [], tagging: [], scheduling: [], publishing: [] },
};
let mktLogs      = [];
let mktLogLevel  = "all";
let mktEpEdit    = null;
let _mktBatchLastFired = "";

function saveMktState() {
  localStorage.setItem(MKT_KEY, JSON.stringify(mktState));
  _cnScheduleSync();
}

function loadMktState() {
  try {
    const raw = localStorage.getItem(MKT_KEY);
    if (!raw) return;
    const p = JSON.parse(raw);
    mktState = {
      folderName: p.folderName || "",
      usedKeys:   p.usedKeys   || [],
      dismissedKeys: p.dismissedKeys || [],
      episodes: {
        production: p.episodes?.production || [],
        tagging:    p.episodes?.tagging    || [],
        scheduling: p.episodes?.scheduling || [],
        publishing: p.episodes?.publishing || [],
      },
    };
  } catch (e) {}
}

function saveMktLogs() {
  localStorage.setItem(MKT_LOG_KEY, JSON.stringify(mktLogs.slice(-MKT_MAX_LOG)));
}

function loadMktLogs() {
  try {
    const raw = localStorage.getItem(MKT_LOG_KEY);
    if (raw) mktLogs = JSON.parse(raw);
  } catch (e) {}
}

// ── Logging ───────────────────────────────────────────────────────────────────
function mktLog(level, msg) {
  const entry = { ts: new Date().toISOString(), level, msg };
  mktLogs.push(entry);
  if (mktLogs.length > MKT_MAX_LOG) mktLogs.shift();
  saveMktLogs();
  _appendMktLogLine(entry);
}

const LOG_LEVEL_COLORS = { info: "#7affc1", warn: "#ffde6b", error: "#ff7bab", debug: "#6dc6ff" };

function _appendMktLogLine(entry, skipBadge = false) {
  const out = document.getElementById("mktLogOutput");
  if (!out) return;
  if (mktLogLevel !== "all" && entry.level !== mktLogLevel) return;
  if (out.textContent === "Waiting for events…") out.textContent = "";
  const time  = entry.ts.replace("T", " ").slice(0, 19);
  const lvl   = entry.level.toUpperCase().padEnd(5);
  const color = LOG_LEVEL_COLORS[entry.level] || "#b8cde4";
  const line  = document.createElement("span");
  line.style.color = color;
  line.textContent = `[${time}] ${lvl} │ ${entry.msg}\n`;
  out.appendChild(line);
  const autoScroll = document.getElementById("mktAutoScroll");
  if (!autoScroll || autoScroll.checked) out.scrollTop = out.scrollHeight;
  // Bump badge only for live entries (not historical replay)
  if (!skipBadge) {
    const tailEl = document.getElementById("mktFloatTail");
    if (!tailEl || !tailEl.classList.contains("open")) _mktBumpBadge();
  }
}

function renderMktLogs() {
  const out = document.getElementById("mktLogOutput");
  if (!out) return;
  out.textContent = "";
  const filtered = mktLogLevel === "all" ? mktLogs : mktLogs.filter(e => e.level === mktLogLevel);
  if (!filtered.length) { out.textContent = "No log entries."; return; }
  // skipBadge=true — historical replay must not inflate the counter
  filtered.forEach(e => _appendMktLogLine(e, true));
}

// ── Utilities ─────────────────────────────────────────────────────────────────
function mktFmtSize(bytes) {
  if (bytes < 1024)        return bytes + " B";
  if (bytes < 1048576)     return (bytes / 1024).toFixed(1) + " KB";
  if (bytes < 1073741824)  return (bytes / 1048576).toFixed(1) + " MB";
  return (bytes / 1073741824).toFixed(2) + " GB";
}

function mktFmtAge(ms) {
  const s = Math.floor((Date.now() - ms) / 1000);
  if (s < 60)    return s + "s ago";
  if (s < 3600)  return Math.floor(s / 60) + "m ago";
  return Math.floor(s / 3600) + "h ago";
}

function mktEpKey(filename, size) { return filename + "||" + size; }

function _allMktKeys() {
  const s = mktState.episodes;
  return new Set([
    ...s.production.map(e => e.key),
    ...s.tagging.map(e => e.key),
    ...s.scheduling.map(e => e.key),
    ...s.publishing.map(e => e.key),
  ]);
}

// ── Auto-advance helpers ──────────────────────────────────────────────────────

function mktDeriveTitle(filename) {
  return filename
    .replace(/\.mp4$/i, "")
    .replace(/_/g, " ")
    .replace(/\b\w/g, c => c.toUpperCase());
}

function mktNextBatchSlot() {
  const amsNow = new Date(new Date().toLocaleString("en-US", { timeZone: "Europe/Amsterdam" }));
  const curMin = amsNow.getHours() * 60 + amsNow.getMinutes();
  const minSlot = curMin + 60; // slot must be at least 1 hour from now
  return MKT_BATCH_SLOTS.find(s => {
    const [h, m] = s.split(":").map(Number);
    return h * 60 + m >= minSlot;
  }) || MKT_BATCH_SLOTS[0]; // wraps to 07:00 next day if no slot qualifies today
}

// First MKT_PUB_SLOTS entry strictly after the given batchSlot; wraps to [0] next day.
function mktAirSlotForBatch(batchSlot) {
  const [bh, bm] = batchSlot.split(":").map(Number);
  const batchMin = bh * 60 + bm;
  return MKT_PUB_SLOTS.find(s => {
    const [h, m] = s.split(":").map(Number);
    return h * 60 + m > batchMin;
  }) || MKT_PUB_SLOTS[0]; // wraps: e.g. upload 20:00 → air 08:00 next day
}

// Auto-advance: skip manual stages, push straight to Scheduling with all metadata pre-filled.
function mktAutoAdvanceToPublishing(ep) {
  const title = mktDeriveTitle(ep.filename);

  // ── Resolve upload/publish slots ──────────────────────────────────────────────
  // If the backend pre-assigned a batch schedule, use it directly (exact datetimes).
  // Otherwise fall back to the next available batch slot.
  let slot, airSlot, uploadDate, scheduledPublishAt;
  if (ep.scheduledPublishAt) {
    scheduledPublishAt = ep.scheduledPublishAt;
    // Parse AMS wall-clock time from the ISO string
    const pubLocal = new Date(new Date(ep.scheduledPublishAt).toLocaleString("en-US", { timeZone: "Europe/Amsterdam" }));
    airSlot    = `${String(pubLocal.getHours()).padStart(2,"0")}:${String(pubLocal.getMinutes()).padStart(2,"0")}`;
    const uplSrc = ep.scheduledUploadAt ? new Date(ep.scheduledUploadAt) : new Date(new Date(ep.scheduledPublishAt) - 3600000);
    const uplLocal = new Date(uplSrc.toLocaleString("en-US", { timeZone: "Europe/Amsterdam" }));
    slot       = `${String(uplLocal.getHours()).padStart(2,"0")}:${String(uplLocal.getMinutes()).padStart(2,"0")}`;
    uploadDate = `${uplLocal.getFullYear()}-${String(uplLocal.getMonth()+1).padStart(2,"0")}-${String(uplLocal.getDate()).padStart(2,"0")}`;
  } else {
    slot               = mktNextBatchSlot();
    airSlot            = mktAirSlotForBatch(slot);
    uploadDate         = "";
    scheduledPublishAt = "";
  }

  // Stage 2 — auto-fill metadata (use Claude-generated title/description if available)
  const finalTitle = ep.youtubeTitle || title;
  const keywords = finalTitle.toLowerCase().replace(/[^a-z0-9 ]/g, "").split(/\s+/).filter(w => w.length > 3);
  ep.title       = finalTitle;
  ep.tags        = ep.youtubeTags?.length ? ep.youtubeTags : [...new Set([...keywords, "documentary", "education"])];
  ep.category    = "27";
  ep.privacy     = "private";
  ep.language    = ep.youtubeLanguage  || "en";
  ep.audience    = ep.youtubeAudience  || "general";
  ep.description = ep.youtubeDescription || `${finalTitle}.\n\nAn auto-generated documentary.`;
  ep.movedToTagAt = Date.now();

  // Stage 3 — schedule with exact dates so the batch trigger fires on the right day
  ep.batchSlot         = slot;
  ep.airSlot           = airSlot;
  ep.uploadDate        = uploadDate;
  ep.scheduledPublishAt = scheduledPublishAt;
  ep.movedToScheduleAt = Date.now();

  // Stage 4 — ready for upload
  ep.uploadStatus     = "pending";
  ep.movedToPublishAt = Date.now();

  mktState.episodes.scheduling.push(ep);
  const schedLabel = scheduledPublishAt
    ? `Publish ${scheduledPublishAt.slice(0,10)} @ ${airSlot} AMS`
    : `Upload ${slot} AMS → Air ${airSlot} AMS`;
  mktLog("info", `Auto-queued: "${title}" → ${schedLabel}`);
}

// ── Auto-scan: polls /api/output/new-videos every 10 s ───────────────────────
let _mktScanTimer = null;

// Remove stale done/error entries from Publishing and protect their keys from re-queuing.
function _mktArchiveDone() {
  const now = Date.now();
  let changed = false;
  const keep = [];
  mktState.episodes.publishing.forEach(ep => {
    const age     = now - (ep.movedToPublishAt || 0);
    const isDone  = ep.uploadStatus === "done"  && age > MKT_ARCHIVE_DONE_MS;
    const isError = ep.uploadStatus === "error" && age > MKT_ARCHIVE_ERROR_MS;
    if (isDone || isError) {
      if (!mktState.usedKeys.includes(ep.key)) mktState.usedKeys.push(ep.key);
      mktLog("info", `Auto-archived: "${ep.title || ep.filename}" (${ep.uploadStatus})`);
      changed = true;
    } else {
      keep.push(ep);
    }
  });
  if (changed) {
    mktState.episodes.publishing = keep;
    saveMktState();
    renderMktKanban();
  }
}

// Run once at init — fixes localStorage state from old code versions, independent of scan success.
function _mktMigrate() {
  let changed = false;

  // Move pending items that ended up in Publishing (old bug) back to Scheduling with airSlot set
  const misplaced = mktState.episodes.publishing.filter(ep => ep.uploadStatus === "pending" && ep.batchSlot);
  if (misplaced.length) {
    mktState.episodes.publishing = mktState.episodes.publishing.filter(ep => !(ep.uploadStatus === "pending" && ep.batchSlot));
    misplaced.forEach(ep => { if (!ep.airSlot) ep.airSlot = mktAirSlotForBatch(ep.batchSlot); });
    const schedKeys = new Set(mktState.episodes.scheduling.map(e => e.key));
    misplaced.filter(ep => !schedKeys.has(ep.key)).forEach(ep => mktState.episodes.scheduling.push(ep));
    mktLog("info", `Migrated ${misplaced.length} pending item(s) Publishing → Scheduling`);
    changed = true;
  }

  // Reset stuck "uploading" episodes — page was refreshed or server restarted mid-upload.
  // After 30 min the upload must have either completed or failed; mark error so user can recover.
  const _STALE_MS = 30 * 60 * 1000;
  mktState.episodes.publishing.forEach(ep => {
    if (ep.uploadStatus === "uploading") {
      const age = ep.movedToPublishAt ? Date.now() - ep.movedToPublishAt : _STALE_MS + 1;
      if (age > _STALE_MS) {
        ep.uploadStatus = "error";
        ep.errorMsg = ep.errorMsg || "Upload interrupted — verify on YouTube Studio, then click Mark Done ✓";
        mktLog("warn", `Stale upload reset: "${ep.title || ep.filename}" — verify on YouTube`);
        changed = true;
      }
    }
  });

  // Re-slot pending episodes still on a removed batch slot (00/04/08/12/16/20, dropped 2026-09-11)
  // onto the next kept slot — _mktCheckBatch only fires exact slot matches, so they would never upload.
  // The next kept slot always feeds the same air slot, so airSlot / publish time stay unchanged.
  mktState.episodes.scheduling.forEach(ep => {
    if (ep.uploadStatus !== "pending" || !ep.batchSlot || MKT_BATCH_SLOTS.includes(ep.batchSlot)) return;
    const [oh, om] = ep.batchSlot.split(":").map(Number);
    const next = MKT_BATCH_SLOTS.find(s => {
      const [h, m] = s.split(":").map(Number);
      return h * 60 + m > oh * 60 + om;
    });
    if (!next && ep.uploadDate) {   // e.g. 20:00 → 07:00 the following day
      const d = new Date(ep.uploadDate + "T12:00:00Z");
      d.setUTCDate(d.getUTCDate() + 1);
      ep.uploadDate = d.toISOString().slice(0, 10);
    }
    const newSlot = next || MKT_BATCH_SLOTS[0];
    mktLog("info", `Re-slotted "${ep.title || ep.filename}": batch ${ep.batchSlot} → ${newSlot} AMS`);
    ep.batchSlot = newSlot;
    changed = true;
  });

  // Ensure all scheduling items have airSlot derived from their batchSlot
  mktState.episodes.scheduling.forEach(ep => {
    if (!ep.airSlot && ep.batchSlot) { ep.airSlot = mktAirSlotForBatch(ep.batchSlot); changed = true; }
  });

  if (changed) { saveMktState(); renderMktKanban(); }

  // Archive old done/error entries (runs independently — has its own save/render)
  _mktArchiveDone();
}

async function mktAutoScan() {
  const statusEl = document.getElementById("mktScanStatus");
  if (statusEl) { statusEl.textContent = "Scanning…"; statusEl.className = "mkt-scan-status"; }
  try {
    const res  = await fetch(MKT_SCAN_URL, { cache: "no-store" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    if (statusEl) { statusEl.textContent = `Scanned · ${data.total} file(s)`; }

    const scanKeys  = new Set((data.videos || []).map(v => mktEpKey(v.filename, v.size)));
    // Keys already in any downstream queue (skip re-queuing, but still show in Stage 1)
    const queueKeys = new Set([
      ...new Set(mktState.usedKeys || []),
      ...mktState.episodes.tagging.map(e => e.key),
      ...mktState.episodes.scheduling.map(e => e.key),
      ...mktState.episodes.publishing.map(e => e.key),
    ]);
    // Dismissed keys — local plus whatever the server knows (covers a dismissal
    // made in another tab, or before this tab's localStorage was written).
    const dismissed  = new Set([...(mktState.dismissedKeys || []), ...(data.dismissed || [])]);
    const dismissedF = new Set(data.dismissed_files || []);
    // Keys already shown in Stage 1
    const prod1Keys = new Set(mktState.episodes.production.map(e => e.key));
    let changed = false;

    // Server-side dismissals win over anything this tab still holds queued.
    if (dismissed.size || dismissedF.size) {
      const isDead = ep => dismissed.has(ep.key) || dismissedF.has(ep.filename);
      ["production", "tagging", "scheduling", "publishing"].forEach(s => {
        const stale = mktState.episodes[s].filter(isDead);
        if (!stale.length) return;
        mktState.episodes[s] = mktState.episodes[s].filter(ep => !isDead(ep));
        stale.forEach(ep => {
          if (!mktState.dismissedKeys.includes(ep.key)) mktState.dismissedKeys.push(ep.key);
          mktLog("info", `🚫 Dropped dismissed episode from ${s}: "${ep.title || ep.filename}"`);
        });
        changed = true;
      });
    }

    (data.videos || []).forEach(v => {
      const key = mktEpKey(v.filename, v.size);
      if (dismissed.has(key) || dismissedF.has(v.filename)) return;  // dismissed — never re-queue
      const ep  = { key, filename: v.filename, size: v.size, lastModified: v.modified_ts, pipelineId: v.pipeline_id,
                    youtubeTitle: v.youtube_title || "", youtubeDescription: v.youtube_description || "",
                    youtubeTags: v.youtube_tags || [], youtubeLanguage: v.youtube_language || "en",
                    youtubeAudience: v.youtube_audience || "general", addedAt: Date.now(),
                    scheduledPublishAt: v.scheduled_publish_at || "",
                    scheduledUploadAt:  v.scheduled_upload_at  || "" };

      // Keep Stage 1 as a running 24h log — add if not already there
      if (!prod1Keys.has(key)) {
        mktState.episodes.production.push({ ...ep });
        prod1Keys.add(key);
        const hasMeta = v.youtube_title ? " (YouTube meta from Claude)" : "";
        mktLog("info", `Detected: ${v.filename} (${mktFmtSize(v.size)}, ${mktFmtAge(v.modified_ts)})${hasMeta}`);
        changed = true;
      }

      // Auto-advance to Scheduling if not already in any queue
      if (!queueKeys.has(key)) {
        mktAutoAdvanceToPublishing({ ...ep });
        queueKeys.add(key);
        changed = true;
      }
    });

    // Prune Stage 1 entries whose files no longer appear in scan results (deleted or outside age window)
    const before = mktState.episodes.production.length;
    mktState.episodes.production = mktState.episodes.production.filter(ep => scanKeys.has(ep.key));
    if (mktState.episodes.production.length !== before) {
      mktLog("info", `Pruned ${before - mktState.episodes.production.length} stale Stage 1 entry/entries`);
      changed = true;
    }

    if (changed) { saveMktState(); renderMktKanban(); }
    mktLog("debug", `Scan complete — ${data.total} total on disk`);
  } catch (e) {
    if (statusEl) { statusEl.textContent = "Scan error"; statusEl.className = "mkt-scan-status mkt-scan-error"; }
    mktLog("error", `Auto-scan failed: ${e.message}`);
  }
}

function mktStartAutoScan() {
  mktAutoScan();
  _mktScanTimer = setInterval(mktAutoScan, MKT_SCAN_INTERVAL);
}

// ── Stage transitions ─────────────────────────────────────────────────────────
function mktMoveToTagging(key) {
  const idx = mktState.episodes.production.findIndex(e => e.key === key);
  if (idx === -1) return;
  const ep = mktState.episodes.production.splice(idx, 1)[0];
  ep.movedToTagAt = Date.now();
  mktState.episodes.tagging.push(ep);
  mktLog("info", `→ Tagging: ${ep.filename}`);
  saveMktState(); renderMktKanban();
}

function mktMoveToScheduling(key) {
  const ep = mktState.episodes.tagging.find(e => e.key === key);
  if (!ep) return;
  if (!ep.title) { mktLog("warn", `Cannot schedule "${ep.filename}" — set a title first.`); return; }
  mktState.episodes.tagging = mktState.episodes.tagging.filter(e => e.key !== key);
  ep.movedToScheduleAt = Date.now();
  mktState.episodes.scheduling.push(ep);
  mktLog("info", `→ Scheduling: ${ep.title}`);
  saveMktState(); renderMktKanban();
}

function mktMoveToPublishing(key) {
  const ep = mktState.episodes.scheduling.find(e => e.key === key);
  if (!ep) return;
  if (!ep.batchSlot) { mktLog("warn", `Cannot publish "${ep.title}" — assign a batch slot first.`); return; }
  mktState.episodes.scheduling = mktState.episodes.scheduling.filter(e => e.key !== key);
  ep.movedToPublishAt = Date.now();
  ep.uploadStatus = "pending";
  mktState.episodes.publishing.push(ep);
  mktLog("info", `→ Publishing queue: ${ep.title} @ ${ep.batchSlot}`);
  saveMktState(); renderMktKanban();
}

// Dismiss = kill the episode everywhere.
//
// The auto-scan pushes a *clone* of every detected file straight into the
// Scheduling queue (mktAutoAdvanceToPublishing) at the same moment it adds the
// Stage 1 card. Removing only the Stage 1 card therefore left that clone armed,
// and the batch trigger uploaded it anyway. Dismissal must:
//   1. drop the episode from all four stage queues,
//   2. remember the key so the next 10 s scan cannot re-queue it, and
//   3. tell the backend, which hides the file from the scanner and refuses the
//      upload outright — the only guarantee that survives a stale browser tab.
function mktDismissEpisode(key, opts = {}) {
  const stages = ["production", "tagging", "scheduling", "publishing"];
  let ep = null;
  stages.forEach(s => {
    const hit = mktState.episodes[s].find(e => e.key === key);
    if (hit && !ep) ep = hit;
    mktState.episodes[s] = mktState.episodes[s].filter(e => e.key !== key);
  });
  if (!mktState.dismissedKeys.includes(key)) mktState.dismissedKeys.push(key);
  if (!mktState.usedKeys.includes(key))      mktState.usedKeys.push(key);
  saveMktState();
  renderMktKanban();

  if (!ep) return;
  const label   = ep.title || ep.filename;
  const wasSent = ep.uploadStatus === "uploading" || ep.uploadStatus === "done";
  mktLog("info", `🚫 Dismissed: "${label}" — removed from all stages, will not upload.`);
  if (wasSent) {
    mktLog("warn", `"${label}" was already ${ep.uploadStatus === "done" ? "uploaded" : "uploading"} — ` +
                   `delete or unschedule it in YouTube Studio; dismissing only clears this board.`);
  }

  // Persist server-side so the scanner and the uploader both honour it.
  if (opts.local) return;
  fetch(MKT_DISMISS_URL, {
    method:  "POST",
    headers: { "Content-Type": "application/json" },
    body:    JSON.stringify({
      key,
      filename:    ep.filename,
      size:        ep.size,
      pipeline_id: ep.pipelineId || "",
      title:       ep.title      || "",
    }),
  })
  .then(r => r.json())
  .then(res => {
    if (res.success) mktLog("debug", `Dismissal registered on server: ${ep.filename}`);
    else             mktLog("error", `Server refused dismissal: ${res.error || "unknown"} — it may re-appear on the next scan.`);
  })
  .catch(err => mktLog("error", `Dismissal not saved on server (${err.message}) — it may re-appear on the next scan.`));
}

// Back-compat alias — Stage 1 button used to call this.
function mktRemoveFromProduction(key) { mktDismissEpisode(key); }

// ── Tag modal ─────────────────────────────────────────────────────────────────
function openMktTagModal(key) {
  const ep = mktState.episodes.tagging.find(e => e.key === key);
  if (!ep) return;
  mktEpEdit = { key, stage: "tagging" };
  state.openDialogType = "__mkt_tag__";
  el.modalTitle.textContent = "Tag Episode";
  el.modalBody.innerHTML = `
    <div class="modal-field">
      <label class="modal-label">File</label>
      <input class="modal-input" value="${esc(ep.filename)}" readonly style="opacity:0.45" />
    </div>
    <div class="modal-field">
      <label class="modal-label">Title *</label>
      <input id="mkt-md-title" class="modal-input" type="text" placeholder="Episode title" value="${esc(ep.title||"")}" />
    </div>
    <div class="modal-field">
      <label class="modal-label">Description</label>
      <textarea id="mkt-md-desc" class="modal-input" rows="3" placeholder="Episode description…">${esc(ep.description||"")}</textarea>
    </div>
    <div class="modal-field">
      <label class="modal-label">Tags (comma-separated)</label>
      <input id="mkt-md-tags" class="modal-input" type="text" placeholder="documentary, history, zygomatic" value="${esc((ep.tags||[]).join(", "))}" />
    </div>
    <div class="modal-field">
      <label class="modal-label">Category</label>
      <select id="mkt-md-cat" class="modal-input" style="color-scheme:dark;background:#0c1624;border:1px solid #2e435f;border-radius:10px;color:var(--text);padding:8px 12px;font-size:0.88rem;width:100%">
        <option value="27" ${(ep.category||"27")==="27"?"selected":""}>Education (27)</option>
        <option value="22" ${ep.category==="22"?"selected":""}>People &amp; Blogs (22)</option>
        <option value="25" ${ep.category==="25"?"selected":""}>News &amp; Politics (25)</option>
        <option value="28" ${ep.category==="28"?"selected":""}>Science &amp; Technology (28)</option>
        <option value="19" ${ep.category==="19"?"selected":""}>Travel &amp; Events (19)</option>
        <option value="2"  ${ep.category==="2" ?"selected":""}>Autos &amp; Vehicles (2)</option>
        <option value="24" ${ep.category==="24"?"selected":""}>Entertainment (24)</option>
        <option value="17" ${ep.category==="17"?"selected":""}>Sports (17)</option>
      </select>
    </div>
    <div class="modal-field">
      <label class="modal-label">Privacy</label>
      <select id="mkt-md-priv" class="modal-input" style="color-scheme:dark;background:#0c1624;border:1px solid #2e435f;border-radius:10px;color:var(--text);padding:8px 12px;font-size:0.88rem;width:100%">
        <option value="private"  ${(ep.privacy||"private")==="private"  ?"selected":""}>Private</option>
        <option value="unlisted" ${ep.privacy==="unlisted"?"selected":""}>Unlisted</option>
        <option value="public"   ${ep.privacy==="public"  ?"selected":""}>Public</option>
      </select>
    </div>`;
  el.modal.classList.add("open");
  el.modalSave.style.display = "";
  setTimeout(() => document.getElementById("mkt-md-title")?.focus(), 50);
}

// ── Schedule modal ────────────────────────────────────────────────────────────
function openMktScheduleModal(key) {
  const ep = mktState.episodes.scheduling.find(e => e.key === key);
  if (!ep) return;
  mktEpEdit = { key, stage: "scheduling" };
  state.openDialogType = "__mkt_schedule__";
  el.modalTitle.textContent = "Schedule Episode";
  el.modalBody.innerHTML = `
    <div class="modal-field">
      <label class="modal-label">Episode</label>
      <input class="modal-input" value="${esc(ep.title||ep.filename)}" readonly style="opacity:0.45" />
    </div>
    <div class="modal-field">
      <label class="modal-label">Upload Date</label>
      <input id="mkt-md-date" class="modal-input" type="date" value="${esc(ep.uploadDate||"")}" />
    </div>
    <div class="modal-field">
      <label class="modal-label">Batch Slot (AMS time)</label>
      <select id="mkt-md-slot" class="modal-input" style="color-scheme:dark;background:#0c1624;border:1px solid #2e435f;border-radius:10px;color:var(--text);padding:8px 12px;font-size:0.88rem;width:100%">
        ${MKT_BATCH_SLOTS.map(s => `<option value="${s}" ${ep.batchSlot===s?"selected":""}>${s}</option>`).join("")}
      </select>
      <div class="telemetry-note" style="margin-top:6px">3 upload slots per day · each airs 1 h later (08:00 · 14:00 · 20:00)</div>
    </div>`;
  el.modal.classList.add("open");
  el.modalSave.style.display = "";
}

// ── Save handlers (called from saveDialog) ────────────────────────────────────
function saveMktTagModal() {
  if (!mktEpEdit) return;
  const ep = mktState.episodes[mktEpEdit.stage]?.find(e => e.key === mktEpEdit.key);
  if (!ep) { closeDialog(); return; }
  ep.title       = (document.getElementById("mkt-md-title")?.value || "").trim();
  ep.description = (document.getElementById("mkt-md-desc")?.value  || "").trim();
  ep.tags        = (document.getElementById("mkt-md-tags")?.value  || "")
                     .split(",").map(t => t.trim()).filter(Boolean);
  ep.category    = document.getElementById("mkt-md-cat")?.value  || "27";
  ep.privacy     = document.getElementById("mkt-md-priv")?.value || "private";
  ep.taggedAt    = Date.now();
  mktLog("info", `Tagged: "${ep.title}" [${ep.privacy} · cat ${ep.category} · ${ep.tags.length} tags]`);
  saveMktState();
  closeDialog();
  renderMktKanban();
}

function saveMktScheduleModal() {
  if (!mktEpEdit) return;
  const ep = mktState.episodes[mktEpEdit.stage]?.find(e => e.key === mktEpEdit.key);
  if (!ep) { closeDialog(); return; }
  ep.uploadDate  = document.getElementById("mkt-md-date")?.value || "";
  ep.batchSlot   = document.getElementById("mkt-md-slot")?.value || MKT_BATCH_SLOTS[0];
  ep.scheduledAt = Date.now();
  mktLog("info", `Scheduled: "${ep.title}" → ${ep.batchSlot}${ep.uploadDate ? " on " + ep.uploadDate : ""}`);
  saveMktState();
  closeDialog();
  renderMktKanban();
}

// ── Render functions ──────────────────────────────────────────────────────────
function _renderMktProduction() {
  const body  = document.getElementById("mkt-body-production");
  const count = document.getElementById("mkt-count-production");
  if (!body) return;
  const eps = mktState.episodes.production;
  if (count) count.textContent = eps.length;
  if (!eps.length) { body.innerHTML = ""; return; }
  body.innerHTML = eps.map(ep => `
    <div class="mkt-ep-card">
      <div class="mkt-ep-filename">${esc(ep.filename)}</div>
      <div class="mkt-ep-meta">
        <span>${mktFmtSize(ep.size)}</span>
        <span>${mktFmtAge(ep.lastModified)}</span>
      </div>
      <div class="mkt-ep-actions">
        <button class="mkt-ep-btn mkt-ep-btn--primary" data-mkt-to-tag="${esc(ep.key)}">Tag</button>
        <button class="mkt-ep-btn mkt-ep-btn--danger"  data-mkt-remove="${esc(ep.key)}">Dismiss</button>
      </div>
    </div>`).join("");
  body.querySelectorAll("[data-mkt-to-tag]").forEach(b =>
    b.addEventListener("click", () => mktMoveToTagging(b.dataset.mktToTag)));
  body.querySelectorAll("[data-mkt-remove]").forEach(b =>
    b.addEventListener("click", () => mktRemoveFromProduction(b.dataset.mktRemove)));
}

const _MKT_TAG_TASKS = [
  "Set video title",
  "Add tags (keywords)",
  "Set category",
  "Set privacy (Public / Unlisted)",
  "Write description",
];

function _renderMktTagging() {
  const body  = document.getElementById("mkt-body-tagging");
  const count = document.getElementById("mkt-count-tagging");
  if (!body) return;
  const eps = mktState.episodes.tagging;
  if (count) count.textContent = eps.length;
  const taskListHtml = `
    <div class="mkt-stage-tasks">
      ${_MKT_TAG_TASKS.map(t => `<div class="mkt-stage-task">${t}</div>`).join("")}
    </div>`;
  if (!eps.length) { body.innerHTML = taskListHtml; return; }
  body.innerHTML = taskListHtml + eps.map(ep => `
    <div class="mkt-ep-card">
      <div class="mkt-ep-filename">${esc(ep.title || ep.filename)}</div>
      ${!ep.title ? `<div class="mkt-ep-meta"><span>${mktFmtSize(ep.size)}</span></div>` : ""}
      ${ep.tags?.length ? `<div class="mkt-ep-tags">${ep.tags.slice(0,5).map(t => `<span class="mkt-tag-chip">${esc(t)}</span>`).join("")}${ep.tags.length>5?`<span class="mkt-tag-chip">+${ep.tags.length-5}</span>`:""}</div>` : ""}
      ${ep.privacy ? `<div class="mkt-ep-meta"><span>${esc(ep.privacy)}</span>${ep.category?`<span>${esc(ep.category)}</span>`:""}</div>` : ""}
      <div class="mkt-ep-actions">
        <button class="mkt-ep-btn" data-mkt-open-tag="${esc(ep.key)}">Edit Tags</button>
        ${ep.title ? `<button class="mkt-ep-btn mkt-ep-btn--primary" data-mkt-to-sched="${esc(ep.key)}">Schedule</button>` : ""}
      </div>
    </div>`).join("");
  body.querySelectorAll("[data-mkt-open-tag]").forEach(b =>
    b.addEventListener("click", () => openMktTagModal(b.dataset.mktOpenTag)));
  body.querySelectorAll("[data-mkt-to-sched]").forEach(b =>
    b.addEventListener("click", () => mktMoveToScheduling(b.dataset.mktToSched)));
}

function _renderMktScheduling() {
  const body  = document.getElementById("mkt-body-scheduling");
  const count = document.getElementById("mkt-count-scheduling");
  if (!body) return;
  const eps = mktState.episodes.scheduling;
  if (count) count.textContent = eps.length;

  const bySlot = {};
  MKT_BATCH_SLOTS.forEach(s => { bySlot[s] = []; });
  eps.forEach(ep => {
    const slot = ep.batchSlot && bySlot[ep.batchSlot] !== undefined ? ep.batchSlot : MKT_BATCH_SLOTS[0];
    bySlot[slot].push(ep);
  });

  const STATUS = {
    pending:   `<span class="mkt-status-chip mkt-status-pending">Pending</span>`,
    uploading: `<span class="mkt-status-chip mkt-status-uploading">Uploading…</span>`,
    done:      `<span class="mkt-status-chip mkt-status-done">Done</span>`,
    error:     `<span class="mkt-status-chip mkt-status-error">Error</span>`,
  };

  body.innerHTML = `<div class="mkt-slots-grid">
    ${MKT_BATCH_SLOTS.map(s => {
      const slotEps = bySlot[s];
      const hasEps  = slotEps.length > 0;
      const sid     = "mkt-sl-" + s.replace(":", "");
      return `<div class="mkt-pub-slot-row">
        <button class="mkt-slot-pill${hasEps ? " mkt-slot-pill--active" : ""}" data-slot="${s}" data-sid="${sid}">
          <span>${s} <span>AMS</span></span>
          ${hasEps ? `<span class="mkt-slot-count-badge">${slotEps.length}</span>` : ""}
        </button>
        ${hasEps ? `<div class="mkt-slot-ep-list" id="${sid}">
          ${slotEps.map(ep => `<div class="mkt-ep-card mkt-ep-card--sm">
            <div class="mkt-ep-filename">${esc(ep.title || ep.filename)}</div>
            <div class="mkt-ep-meta" style="margin-top:4px;display:flex;align-items:center;gap:8px">
              <span>${mktFmtSize(ep.size)}</span>
              ${STATUS[ep.uploadStatus] || STATUS.pending}
            </div>
            ${ep.uploadDate ? `<div class="mkt-ep-meta" style="margin-top:2px;font-size:0.75rem;opacity:0.7">
              📤 ${ep.uploadDate} ${ep.batchSlot} AMS${ep.airSlot ? ` · 📡 Publish ${ep.scheduledPublishAt ? ep.scheduledPublishAt.slice(0,10) : ep.uploadDate} ${ep.airSlot} AMS` : ""}
            </div>` : ""}
            <div class="mkt-ep-actions" style="margin-top:6px">
              <button class="mkt-ep-btn mkt-ep-btn--danger" data-mkt-dismiss="${esc(ep.key)}">Dismiss</button>
            </div>
          </div>`).join("")}
        </div>` : ""}
      </div>`;
    }).join("")}
  </div>`;

  body.querySelectorAll(".mkt-slot-pill[data-sid]").forEach(btn => {
    btn.addEventListener("click", () => {
      const list = document.getElementById(btn.dataset.sid);
      if (!list) return;
      const open = list.classList.toggle("mkt-slot-ep-list--open");
      btn.classList.toggle("mkt-slot-pill--expanded", open);
    });
  });

  _mktBindDismissButtons(body);
}

// Shared by every stage: a dismiss button cancels the queued upload outright.
function _mktBindDismissButtons(root) {
  root.querySelectorAll("[data-mkt-dismiss]").forEach(btn => {
    btn.addEventListener("click", e => {
      e.stopPropagation();
      const key = btn.dataset.mktDismiss;
      const ep  = ["production", "tagging", "scheduling", "publishing"]
                    .flatMap(s => mktState.episodes[s]).find(x => x.key === key);
      const name = ep ? (ep.title || ep.filename) : key;
      const sent = ep && (ep.uploadStatus === "uploading" || ep.uploadStatus === "done");
      const msg  = sent
        ? `"${name}" has already been sent to YouTube.\n\nDismissing removes it from this board and blocks any retry, but it does NOT delete the video on YouTube — do that in YouTube Studio.\n\nDismiss anyway?`
        : `Dismiss "${name}"?\n\nIt will be removed from every stage and will not be uploaded.`;
      if (!confirm(msg)) return;
      mktDismissEpisode(key);
    });
  });
}

const MKT_PUB_SLOTS = ["08:00", "14:00", "20:00"];

function _renderMktPublishing() {
  const body  = document.getElementById("mkt-body-publishing");
  const count = document.getElementById("mkt-count-publishing");
  if (!body) return;
  const eps = mktState.episodes.publishing;
  if (count) count.textContent = eps.length;

  // Include scheduling episodes that already have an airSlot pre-assigned (show upcoming)
  const upcoming = mktState.episodes.scheduling.filter(ep => ep.airSlot);
  const allEps   = [...eps, ...upcoming];
  if (count) count.textContent = allEps.length;

  const bySlot = {};
  MKT_PUB_SLOTS.forEach(s => { bySlot[s] = []; });
  allEps.forEach(ep => {
    const slot = ep.airSlot && bySlot[ep.airSlot] !== undefined ? ep.airSlot : MKT_PUB_SLOTS[0];
    bySlot[slot].push(ep);
  });

  const STATUS = {
    pending:   (ep) => `<span class="mkt-status-chip mkt-status-pending">Uploading at ${esc(ep.batchSlot || "—")}</span>`,
    uploading: ()   => `<span class="mkt-status-chip mkt-status-uploading">Uploading…</span>`,
    done:      ()   => `<span class="mkt-status-chip mkt-status-done">✓ Uploaded</span>`,
    error:     (ep) => `<span class="mkt-status-chip mkt-status-error">⚠ Interrupted</span>
                        <button class="mkt-retry-btn" data-key="${esc(ep.key)}">↺ Retry</button>
                        <button class="mkt-mark-done-btn" data-key="${esc(ep.key)}">Mark Done ✓</button>`,
  };

  body.innerHTML = `<div class="mkt-slots-grid mkt-pub-slots">
    ${MKT_PUB_SLOTS.map(s => {
      const slotEps = bySlot[s];
      const hasEps  = slotEps.length > 0;
      const sid     = "mkt-pub-" + s.replace(":", "");
      return `<div class="mkt-pub-slot-row">
        <button class="mkt-slot-pill mkt-slot-pill--pub${hasEps ? " mkt-slot-pill--active" : ""}" data-sid="${sid}">
          <span>${s} <span>AMS</span></span>
          ${hasEps ? `<span class="mkt-slot-count-badge">${slotEps.length}</span>` : ""}
        </button>
        ${hasEps ? `<div class="mkt-slot-ep-list" id="${sid}">
          ${slotEps.map(ep => `<div class="mkt-ep-card mkt-ep-card--sm">
            <div class="mkt-ep-filename">${esc(ep.title || ep.filename)}</div>
            <div class="mkt-ep-meta" style="margin-top:4px;display:flex;align-items:center;gap:8px;flex-wrap:wrap">
              <span>${mktFmtSize(ep.size)}</span>
              ${(STATUS[ep.uploadStatus] || STATUS.pending)(ep)}
              ${ep.youtubeId ? `<span style="color:#6dc6ff">ID: ${esc(ep.youtubeId)}</span>` : ""}
            </div>
            ${ep.scheduledPublishAt ? `<div class="mkt-ep-meta" style="margin-top:2px;font-size:0.75rem;opacity:0.7">
              📡 ${ep.scheduledPublishAt.slice(0,10)} at ${ep.airSlot} AMS
            </div>` : ""}
            ${ep.errorMsg ? `<div style="color:#ff7bab;font-size:0.75rem;margin-top:4px">${esc(ep.errorMsg)}</div>` : ""}
            <div class="mkt-ep-actions" style="margin-top:6px">
              <button class="mkt-ep-btn mkt-ep-btn--danger" data-mkt-dismiss="${esc(ep.key)}">Dismiss</button>
            </div>
          </div>`).join("")}
        </div>` : ""}
      </div>`;
    }).join("")}
  </div>`;

  body.querySelectorAll(".mkt-slot-pill[data-sid]").forEach(btn => {
    btn.addEventListener("click", () => {
      const list = document.getElementById(btn.dataset.sid);
      if (!list) return;
      const open = list.classList.toggle("mkt-slot-ep-list--open");
      btn.classList.toggle("mkt-slot-pill--expanded", open);
    });
  });

  body.querySelectorAll(".mkt-retry-btn").forEach(btn => {
    btn.addEventListener("click", e => {
      e.stopPropagation();
      const ep = mktState.episodes.publishing.find(e => e.key === btn.dataset.key);
      if (!ep) return;
      ep.uploadStatus     = "uploading";
      ep.errorMsg         = "";
      ep.movedToPublishAt = Date.now();
      saveMktState();
      renderMktKanban();
      fetch(MKT_UPLOAD_URL, {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify({
          filename:    ep.filename,
          size:        ep.size,
          pipeline_id: ep.pipelineId        || "",
          title:       ep.title             || ep.filename,
          description: ep.description       || "",
          tags:        ep.tags              || [],
          category:    ep.category          || 27,
          privacy:     ep.privacy           || "private",
          publish_at:  ep.scheduledPublishAt || "",
          air_slot:    ep.airSlot           || "",
        }),
      })
      .then(r => r.json())
      .then(res => {
        const pub = mktState.episodes.publishing.find(e => e.key === ep.key);
        if (!pub) return;
        if (res.dismissed) {   // server refused — the episode was dismissed
          mktLog("info", `🚫 Retry refused: "${pub.title || pub.filename}" was dismissed.`);
          mktDismissEpisode(ep.key, { local: true });
          return;
        }
        if (res.success) {
          pub.uploadStatus = "done";
          pub.youtubeId    = res.video_id;
          mktLog("info", `✅ Retry uploaded: "${pub.title}" → https://www.youtube.com/watch?v=${res.video_id}`);
        } else {
          pub.uploadStatus = "error";
          pub.errorMsg     = res.error;
          mktLog("error", `Retry failed: "${pub.title}" — ${res.error}`);
        }
        saveMktState();
        renderMktKanban();
      })
      .catch(err => {
        const pub = mktState.episodes.publishing.find(e => e.key === ep.key);
        if (pub) { pub.uploadStatus = "error"; pub.errorMsg = err.message; }
        mktLog("error", `Retry error: "${ep.title}" — ${err.message}`);
        saveMktState();
        renderMktKanban();
      });
    });
  });

  body.querySelectorAll(".mkt-mark-done-btn").forEach(btn => {
    btn.addEventListener("click", e => {
      e.stopPropagation();
      const ep = mktState.episodes.publishing.find(e => e.key === btn.dataset.key);
      if (ep) { ep.uploadStatus = "done"; ep.errorMsg = ""; saveMktState(); renderMktKanban(); }
    });
  });

  _mktBindDismissButtons(body);
}

function renderMktKanban() {
  _renderMktProduction();
  _renderMktTagging();
  _renderMktScheduling();
  _renderMktPublishing();
}

// ── Next-batch countdown ──────────────────────────────────────────────────────
function _mktUpdateNextBatch() {
  const el2 = document.getElementById("mktNextBatch");
  if (!el2) return;
  const amsNow = new Date(new Date().toLocaleString("en-US", { timeZone: "Europe/Amsterdam" }));
  const curMin = amsNow.getHours() * 60 + amsNow.getMinutes();
  let nextSlot = MKT_BATCH_SLOTS.find(s => {
    const [h, m] = s.split(":").map(Number);
    return h * 60 + m > curMin;
  }) || MKT_BATCH_SLOTS[0];
  const [nh, nm] = nextSlot.split(":").map(Number);
  const nextDate = new Date(amsNow);
  nextDate.setHours(nh, nm, 0, 0);
  if (nextDate <= amsNow) nextDate.setDate(nextDate.getDate() + 1);
  const diff = nextDate - amsNow;
  const dh   = Math.floor(diff / 3600000);
  const dm   = Math.floor((diff % 3600000) / 60000);
  const ds   = Math.floor((diff % 60000) / 1000);
  el2.textContent = `${nextSlot} (${String(dh).padStart(2,"0")}:${String(dm).padStart(2,"0")}:${String(ds).padStart(2,"0")})`;
}

// ── Automatic batch trigger (checked every minute) ────────────────────────────
function _mktCheckBatch() {
  const amsNow = new Date(new Date().toLocaleString("en-US", { timeZone: "Europe/Amsterdam" }));
  const curSlot = `${String(amsNow.getHours()).padStart(2,"0")}:${String(amsNow.getMinutes()).padStart(2,"0")}`;
  if (!MKT_BATCH_SLOTS.includes(curSlot))    return;
  if (_mktBatchLastFired === curSlot + amsNow.toDateString()) return;
  _mktBatchLastFired = curSlot + amsNow.toDateString();

  const todayStr = amsNow.toISOString().slice(0, 10);
  const dismissed = new Set(mktState.dismissedKeys || []);
  const ready = mktState.episodes.scheduling.filter(ep =>
    ep.uploadStatus === "pending" &&
    ep.batchSlot    === curSlot  &&
    !dismissed.has(ep.key) &&              // dismissed episodes never upload
    (!ep.uploadDate || ep.uploadDate === todayStr)
  );
  if (!ready.length) { mktLog("debug", `Batch ${curSlot}: nothing to upload.`); return; }

  mktLog("info", `⚡ Batch ${curSlot} triggered — ${ready.length} episode(s)`);

  // Move episodes to publishing immediately (status: uploading), then fire async uploads
  ready.forEach(ep => {
    ep.uploadStatus = "uploading";
    if (!ep.airSlot) ep.airSlot = mktAirSlotForBatch(curSlot);
    ep.movedToPublishAt = Date.now();
    mktLog("info", `Starting upload: "${ep.title || ep.filename}" → airs ${ep.airSlot} AMS`);
  });
  const readyKeys = new Set(ready.map(ep => ep.key));
  mktState.episodes.scheduling = mktState.episodes.scheduling.filter(ep => !readyKeys.has(ep.key));
  mktState.episodes.publishing.push(...ready);
  saveMktState();
  renderMktKanban();

  // Fire actual YouTube uploads via backend
  ready.forEach(ep => {
    fetch(MKT_UPLOAD_URL, {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify({
        filename:    ep.filename,
        size:        ep.size,
        pipeline_id: ep.pipelineId        || "",
        title:       ep.title             || ep.filename,
        description: ep.description       || "",
        tags:        ep.tags              || [],
        category:    ep.category          || 27,
        privacy:     ep.privacy           || "private",
        publish_at:  ep.scheduledPublishAt || "",   // exact ISO datetime from batch schedule
        air_slot:    ep.airSlot           || "",    // fallback time-only slot
      }),
    })
    .then(r => r.json())
    .then(res => {
      const pub = mktState.episodes.publishing.find(e => e.key === ep.key);
      if (!pub) return;
      if (res.dismissed) {   // server refused — the episode was dismissed
        mktLog("info", `🚫 Upload refused: "${pub.title || pub.filename}" was dismissed.`);
        mktDismissEpisode(ep.key, { local: true });
        return;
      }
      if (res.success) {
        pub.uploadStatus = "done";
        pub.youtubeId    = res.video_id;
        mktLog("info", `✅ Uploaded: "${pub.title}" → https://www.youtube.com/watch?v=${res.video_id}`);
      } else {
        pub.uploadStatus = "error";
        pub.errorMsg     = res.error;
        mktLog("error", `Upload failed: "${pub.title}" — ${res.error}`);
      }
      saveMktState();
      renderMktKanban();
    })
    .catch(err => {
      const pub = mktState.episodes.publishing.find(e => e.key === ep.key);
      if (pub) { pub.uploadStatus = "error"; pub.errorMsg = err.message; }
      mktLog("error", `Upload error: "${ep.title}" — ${err.message}`);
      saveMktState();
      renderMktKanban();
    });
  });
}

// ── FAB badge counter (disabled — badge removed) ──────────────────────────────
function _mktBumpBadge() {}
function _mktClearBadge() {}

// ── Workflow switcher ─────────────────────────────────────────────────────────
// The "Workflows" dropdown beside the board title swaps the Marketing Pipeline
// kanban for a per-platform board. Every platform named anywhere in Creator
// Nexus (region platform bars, post platforms, account vault) has an entry.
//
// The platform boards are TEMPLATES: they render the stage columns from
// MKT_WF_STAGE_TEMPLATE and stay empty until a real workflow is defined. To give
// a platform its own workflow later, add an entry to MKT_WF_STAGES keyed by the
// workflow id — nothing else has to change.
const MKT_WF_KEY         = "creator_nexus_mkt_workflow_v1";
const MKT_WF_PIPELINE_ID = "pipeline";

const MKT_WORKFLOWS = [
  // The existing Marketing Pipeline board — always first so it is always
  // reachable from inside any other workflow.
  { id: "pipeline",      title: "Marketing Pipeline", color: "6dc6ff", slug: "",          group: "" },

  { id: "youtube",       title: "YouTube",            color: "FF0000", slug: "youtube",   group: "Global" },
  { id: "kick",          title: "Kick",               color: "53FC18", slug: "kick",      group: "Global" },
  { id: "tiktok",        title: "TikTok",             color: "FE2C55", slug: "tiktok",    group: "Global" },
  { id: "instagram",     title: "Instagram",          color: "E4405F", slug: "instagram", group: "Global" },
  { id: "facebook",      title: "Facebook",           color: "1877F2", slug: "facebook",  group: "Global" },
  { id: "x",             title: "X",                  color: "ffffff", slug: "x",         group: "Global" },
  { id: "whatsapp",      title: "WhatsApp",           color: "25D366", slug: "whatsapp",  group: "Global" },

  { id: "linkedin",      title: "LinkedIn",           color: "0A66C2", slug: "linkedin",  group: "Text & Community" },
  { id: "reddit",        title: "Reddit",             color: "FF4500", slug: "reddit",    group: "Text & Community" },
  { id: "pinterest",     title: "Pinterest",          color: "E60023", slug: "pinterest", group: "Text & Community" },
  { id: "threads",       title: "Threads",            color: "ffffff", slug: "threads",   group: "Text & Community" },
  { id: "quora",         title: "Quora",              color: "B92B27", slug: "quora",     group: "Text & Community" },
  { id: "medium",        title: "Medium",             color: "ffffff", slug: "medium",    group: "Text & Community" },
  { id: "google",        title: "Google Business",    color: "4285F4", slug: "google",    group: "Text & Community" },
  { id: "tumblr",        title: "Tumblr",             color: "6B8FBF", slug: "tumblr",    group: "Text & Community" },
  { id: "discord",       title: "Discord",            color: "5865F2", slug: "discord",   group: "Text & Community" },

  { id: "bilibili",      title: "Bilibili",           color: "00A1D6", slug: "bilibili",  group: "China" },
  { id: "sinaweibo",     title: "Weibo",              color: "E9191F", slug: "sinaweibo", group: "China" },
  { id: "wechat",        title: "WeChat",             color: "07C160", slug: "wechat",    group: "China" },
  { id: "qq",            title: "QQ",                 color: "12B7F5", slug: "qq",        group: "China" },
  { id: "douyin",        title: "Douyin",             color: "FE2C55", slug: "tiktok",    group: "China" },
  { id: "zhihu",         title: "Zhihu",              color: "0084FF", slug: "zhihu",     group: "China" },
  { id: "youku",         title: "Youku",              color: "3DBEFF", slug: "youku",     group: "China" },
  { id: "iqiyi",         title: "iQIYI",              color: "00BE06", slug: "iqiyi",     group: "China" },

  { id: "vk",            title: "VK",                 color: "0077FF", slug: "vk",            group: "Russia & CIS" },
  { id: "telegram",      title: "Telegram",           color: "26A5E4", slug: "telegram",      group: "Russia & CIS" },
  { id: "odnoklassniki", title: "OK.ru",              color: "EE8208", slug: "odnoklassniki", group: "Russia & CIS" },
  { id: "yandex",        title: "Yandex Zen",         color: "FC3F1D", slug: "yandex",        group: "Russia & CIS" },
  { id: "rutube",        title: "Rutube",             color: "A6001B", slug: "rutube",        group: "Russia & CIS" },
];

// Default stage columns for a platform workflow that has no definition yet.
const MKT_WF_STAGE_TEMPLATE = [
  { id: "production", title: "Production", hint: "Content picked up for this platform" },
  { id: "formatting", title: "Formatting", hint: "Aspect ratio · length · captions" },
  { id: "scheduling", title: "Scheduling", hint: "Air slots for this platform", airSlots: true },
  { id: "publishing", title: "Publishing", hint: "Publish · verify · archive" },
];

// Per-platform workflow definitions. Empty on purpose — every platform falls back
// to MKT_WF_STAGE_TEMPLATE until its workflow is written. Shape:
//   tiktok: [ { id: "hook", title: "Hook Cut", hint: "First 3 seconds" }, … ]
const MKT_WF_STAGES = {};

let mktActiveWorkflow = MKT_WF_PIPELINE_ID;

function mktWorkflowById(id) {
  return MKT_WORKFLOWS.find(w => w.id === id) || MKT_WORKFLOWS[0];
}

function mktWorkflowStages(wf) {
  const stages = MKT_WF_STAGES[wf.id];
  return (Array.isArray(stages) && stages.length) ? stages : MKT_WF_STAGE_TEMPLATE;
}

// Grouped in declaration order, so the menu keeps the roster's reading order.
function _mktWfGroups() {
  const out = [];
  MKT_WORKFLOWS.forEach(wf => {
    const label = wf.group || "";
    let bucket = out.find(b => b.label === label);
    if (!bucket) { bucket = { label, items: [] }; out.push(bucket); }
    bucket.items.push(wf);
  });
  return out;
}

function _mktWfIconHtml(wf, size = 16) {
  const cls = `mkt-wf-icon${size >= 20 ? " mkt-wf-icon--lg" : ""}`;
  if (!wf.slug) {
    // Marketing Pipeline — reuse the Marketing tab's funnel glyph
    return `<span class="${cls}" style="--pc:#${wf.color}">
      <svg viewBox="0 0 24 24" fill="none" stroke="#${wf.color}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" width="${size}" height="${size}"><polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"/></svg>
    </span>`;
  }
  return `<span class="${cls}" style="--pc:#${wf.color}">
    <img src="https://cdn.simpleicons.org/${wf.slug}/${wf.color}" alt="" width="${size}" height="${size}">
  </span>`;
}

// Icon CDN miss → swap the broken image for a dot in the brand colour.
function _mktWfBindIconFallback(root) {
  if (!root) return;
  root.querySelectorAll(".mkt-wf-icon img").forEach(img => {
    const fail = () => { img.parentNode?.classList.add("is-fallback"); img.remove(); };
    img.addEventListener("error", fail);
    if (img.complete && img.naturalWidth === 0) fail();
  });
}

function _mktWfStageHint(wf, stage) {
  if (stage.airSlots) {
    const slots = PLATFORM_AIR_SLOTS[wf.id];
    if (slots?.length) return `${slots.join(" · ")} AMS`;
  }
  return stage.hint || "";
}

function renderMktWorkflowMenu() {
  const menu = document.getElementById("mktWorkflowMenu");
  if (!menu) return;
  menu.innerHTML = _mktWfGroups().map((g, gi) => `
    ${gi > 0 ? `<div class="mkt-wf-sep"></div>` : ""}
    ${g.label ? `<div class="mkt-wf-group">${esc(g.label)}</div>` : ""}
    ${g.items.map(wf => `
      <button class="mkt-wf-opt${wf.id === mktActiveWorkflow ? " active" : ""}" type="button" role="menuitem" data-wf="${esc(wf.id)}">
        ${_mktWfIconHtml(wf)}
        <span class="mkt-wf-opt-label">${esc(wf.title)}</span>
        <span class="mkt-wf-opt-check">✓</span>
      </button>`).join("")}
  `).join("");
  _mktWfBindIconFallback(menu);
}

function renderMktWorkflowBoard(wf) {
  const boards = document.getElementById("mktWorkflowBoards");
  if (!boards) return;
  const stages = mktWorkflowStages(wf);
  const custom = Array.isArray(MKT_WF_STAGES[wf.id]) && MKT_WF_STAGES[wf.id].length;
  boards.innerHTML = `
    <div class="mkt-wf-banner" style="--pc:#${wf.color}">
      ${_mktWfIconHtml(wf, 20)}
      <span class="mkt-wf-banner-name">${esc(wf.title)}</span>
      <span class="mkt-wf-banner-note">${custom ? `${stages.length} stages` : "Template — stages are placeholders until this workflow is built"}</span>
    </div>
    <div class="mkt-kanban mkt-kanban--wf" style="--wf-cols:${stages.length}">
      ${stages.map((s, i) => `
        <div class="mkt-stage">
          <div class="mkt-stage-header">
            <span class="mkt-stage-num">${i + 1}</span>
            <span class="mkt-stage-title">${esc(s.title)}</span>
            <span class="mkt-stage-count" id="mkt-wf-count-${esc(wf.id)}-${esc(s.id)}">0</span>
          </div>
          <div class="mkt-stage-hint">${esc(_mktWfStageHint(wf, s))}</div>
          <div class="mkt-stage-body" id="mkt-wf-body-${esc(wf.id)}-${esc(s.id)}">
            <div class="mkt-wf-empty">No steps yet</div>
          </div>
        </div>`).join("")}
    </div>`;
  _mktWfBindIconFallback(boards);
}

function mktOpenWorkflow(id, persist = true) {
  const wf = mktWorkflowById(id);
  mktActiveWorkflow = wf.id;
  const isPipeline = wf.id === MKT_WF_PIPELINE_ID;

  const titleEl  = document.getElementById("mktBoardTitle");
  const pipeline = document.getElementById("mktPipelineKanban");
  const boards   = document.getElementById("mktWorkflowBoards");
  const actions  = document.getElementById("mktHeadActions");

  if (titleEl)  titleEl.textContent = isPipeline ? wf.title : `${wf.title} Workflow`;
  if (pipeline) pipeline.hidden = !isPipeline;
  // scan status + next batch describe the pipeline scanner only
  if (actions)  actions.hidden  = !isPipeline;
  if (boards) {
    boards.hidden = isPipeline;
    if (isPipeline) boards.innerHTML = "";
    else            renderMktWorkflowBoard(wf);
  }

  document.querySelectorAll("#mktWorkflowMenu .mkt-wf-opt").forEach(b =>
    b.classList.toggle("active", b.dataset.wf === wf.id));

  if (persist) { try { localStorage.setItem(MKT_WF_KEY, wf.id); } catch (e) {} }
}

function setupMktWorkflows() {
  const btn  = document.getElementById("mktWorkflowBtn");
  const menu = document.getElementById("mktWorkflowMenu");
  if (!btn || !menu) return;

  let saved = MKT_WF_PIPELINE_ID;
  try { saved = localStorage.getItem(MKT_WF_KEY) || MKT_WF_PIPELINE_ID; } catch (e) {}
  mktActiveWorkflow = MKT_WORKFLOWS.some(w => w.id === saved) ? saved : MKT_WF_PIPELINE_ID;

  renderMktWorkflowMenu();

  const openMenu = () => {
    menu.hidden = false;
    btn.classList.add("open");
    btn.setAttribute("aria-expanded", "true");
  };
  const closeMenu = () => {
    menu.hidden = true;
    btn.classList.remove("open");
    btn.setAttribute("aria-expanded", "false");
  };

  btn.addEventListener("click", e => {
    e.stopPropagation();
    menu.hidden ? openMenu() : closeMenu();
  });
  menu.addEventListener("click", e => {
    e.stopPropagation();
    const opt = e.target.closest(".mkt-wf-opt");
    if (!opt) return;
    closeMenu();
    mktOpenWorkflow(opt.dataset.wf);
  });
  document.addEventListener("click", closeMenu);
  document.addEventListener("keydown", e => {
    if (e.key === "Escape" && !menu.hidden) closeMenu();
  });

  mktOpenWorkflow(mktActiveWorkflow, false);
}

// ── Init ──────────────────────────────────────────────────────────────────────
function initMktKanban() {
  loadMktState();
  loadMktLogs();
  _mktMigrate();   // fix any stale localStorage state before first render
  renderMktKanban();
  renderMktLogs();
  setupMktWorkflows();

  _mktUpdateNextBatch();
  setInterval(_mktUpdateNextBatch, 1000);
  setInterval(_mktCheckBatch, 60000);
  setInterval(_mktArchiveDone, 30 * 60 * 1000); // re-check archive every 30 min

  mktStartAutoScan();

  // ── Clear Done button ──
  document.getElementById("mktClearDoneBtn")?.addEventListener("click", () => {
    const before = mktState.episodes.publishing.length;
    mktState.episodes.publishing.forEach(ep => {
      if (ep.uploadStatus === "done" && !mktState.usedKeys.includes(ep.key))
        mktState.usedKeys.push(ep.key);
    });
    mktState.episodes.publishing = mktState.episodes.publishing.filter(ep => ep.uploadStatus !== "done");
    const removed = before - mktState.episodes.publishing.length;
    if (removed > 0) {
      saveMktState();
      renderMktKanban();
      mktLog("info", `Cleared ${removed} done upload(s) from Publishing.`);
    }
  });

  // ── Clear log ──
  document.getElementById("mktClearLog")?.addEventListener("click", () => {
    mktLogs = [];
    saveMktLogs();
    const out = document.getElementById("mktLogOutput");
    if (out) out.textContent = "";
    mktLog("info", "Log cleared.");
  });

  // ── Level filters ──
  document.querySelectorAll(".mkt-log-filter").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".mkt-log-filter").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      mktLogLevel = btn.dataset.level;
      renderMktLogs();
    });
  });

  // ── Floating FAB ──
  const fab     = document.getElementById("mktTailFab");
  const tailEl  = document.getElementById("mktFloatTail");
  const closeBtn = document.getElementById("mktTailClose");

  function openTail() {
    if (!tailEl) return;
    tailEl.classList.add("open");
    tailEl.setAttribute("aria-hidden", "false");
    if (fab) fab.classList.add("active");
    _mktClearBadge();
    const out = document.getElementById("mktLogOutput");
    if (out) out.scrollTop = out.scrollHeight;
  }
  function closeTail() {
    if (!tailEl) return;
    tailEl.classList.remove("open");
    tailEl.setAttribute("aria-hidden", "true");
    if (fab) fab.classList.remove("active");
  }

  fab?.addEventListener("click", () => {
    tailEl?.classList.contains("open") ? closeTail() : openTail();
  });
  closeBtn?.addEventListener("click", closeTail);
}

function setupRulesChevron(chevronId, listId, addBtnId) {
  const chevron = document.getElementById(chevronId);
  const list    = document.getElementById(listId);
  const addBtn  = document.getElementById(addBtnId);
  if (!chevron || !list) return;
  let collapsed = false;
  chevron.addEventListener("click", () => {
    collapsed = !collapsed;
    chevron.classList.toggle("collapsed", collapsed);
    list.style.display   = collapsed ? "none" : "";
    if (addBtn) addBtn.style.display = collapsed ? "none" : "";
  });
}

// ── Init ──────────────────────────────────────────────────────────────────────
function init() {
  loadState();
  _cnBootRestore();   // async: pulls the workstation copy back if this browser came up empty
  seedAllPolicyRules();
  seedDemoIfEmpty();
  setupTabs();
  setupSubtabs();
  setupRegionSelector();
  setupSchedPlatformPickers();
  initUploadTab();
  initMktKanban();
  setupInlineEdit();
  setupVaultRows();
  renderChannelList();
  fillForm(getSelectedChannel());
  if (getSelectedChannel()) openSubtab("content");
  renderMetrics();

  initAdsense();
  document.getElementById("addRuleBtn")?.addEventListener("click", () => addRuleToList("rules", "rulesList"));
  document.getElementById("addPolicyRuleBtn")?.addEventListener("click", () => addRuleToList("policyRules", "policyRulesList"));
  setupRulesChevron("contentRulesChevron", "rulesList", "addRuleBtn");
  setupRulesChevron("policyRulesChevron", "policyRulesList", "addPolicyRuleBtn");
  document.getElementById("addGeneralPolicyRuleBtn")?.addEventListener("click", () => addRuleToList("generalPolicyRules", "generalPolicyRulesList"));
  setupRulesChevron("generalPolicyRulesChevron", "generalPolicyRulesList", "addGeneralPolicyRuleBtn");

  // Posts modal
  document.getElementById("postModalSave")?.addEventListener("click", savePostModal);
  document.getElementById("postModalCancel")?.addEventListener("click", closePostModal);
  document.getElementById("postModalClose")?.addEventListener("click", closePostModal);
  document.getElementById("postModalDelete")?.addEventListener("click", deletePostModal);
  document.getElementById("postModal")?.addEventListener("click", e => {
    if (e.target === document.getElementById("postModal")) closePostModal();
  });
  document.addEventListener("keydown", e => {
    if (e.key === "Escape" && document.getElementById("postModal")?.classList.contains("open")) closePostModal();
  });

  el.addChannelBtn.addEventListener("click", addChannelFromInput);
  el.newChannelName.addEventListener("keydown", e => {
    if (e.key === "Enter") { e.preventDefault(); addChannelFromInput(); }
  });
  el.deleteChannelBtn.addEventListener("click", () => {
    closeSettings();
    deleteSelectedChannel();
  });

  // Settings gear toggle
  el.settingsBtn.addEventListener("click", e => {
    e.stopPropagation();
    const isOpen = el.settingsMenu.classList.contains("open");
    closeSettings();
    if (!isOpen) {
      el.settingsMenu.classList.add("open");
      el.settingsBtn.classList.add("open");
    }
  });
  document.addEventListener("click", () => closeSettings());

  // Content card click → detail dialog
  document.addEventListener("click", e => {
    const card = e.target.closest("[data-content-card]");
    if (!card) return;
    const title    = card.querySelector(".content-card-title")?.textContent || "Video";
    const views    = card.querySelector(".stat-value")?.textContent || "0";
    const earn     = card.querySelectorAll(".stat-value")[1]?.textContent || "$0.00";
    const hidden   = card.querySelector(".content-card-hidden");
    const likes    = hidden?.querySelector("[data-stat='likes']")?.textContent || "0";
    const comments = hidden?.querySelector("[data-stat='comments']")?.textContent || "0";
    const updated  = hidden?.querySelector("[data-stat='updated']")?.textContent || "—";
    const cpm      = hidden?.querySelector("[data-stat='cpm']")?.textContent || "$0.00";

    el.modalTitle.textContent = title;
    el.modalBody.innerHTML = `
      <div class="modal-field"><label class="modal-label">Views</label><input class="modal-input" value="${views}" readonly /></div>
      <div class="modal-field"><label class="modal-label">Likes</label><input class="modal-input" value="${likes}" readonly /></div>
      <div class="modal-field modal-field--clickable" data-open-comments data-video-title="${title.replace(/"/g,'&quot;')}">
        <label class="modal-label">Comments</label>
        <input class="modal-input" value="${comments}" readonly style="pointer-events:none" />
      </div>
      <div class="modal-field"><label class="modal-label">Updated</label><input class="modal-input" value="${updated}" readonly /></div>
      <div class="modal-field"><label class="modal-label">CPM</label><input class="modal-input" value="${cpm}" readonly /></div>
      <div class="modal-field"><label class="modal-label">Earnings</label><input class="modal-input" value="${earn}" readonly /></div>
    `;
    state.openDialogType = null;
    el.modalSave.style.display = "none";
    el.modal.classList.add("open");
  });

  // Comments field click → nested comments dialog
  document.addEventListener("click", e => {
    const trigger = e.target.closest("[data-open-comments]");
    if (!trigger) return;
    e.stopPropagation();
    const videoTitle = trigger.dataset.videoTitle || "Video";
    openCommentsDialog(videoTitle);
  });

  // Modal events
  el.modalSave.addEventListener("click", saveDialog);
  el.modalCancel.addEventListener("click", () => { el.modalSave.style.display = ""; closeDialog(); });
  el.modalClose.addEventListener("click", () => { el.modalSave.style.display = ""; closeDialog(); });
  el.modal.addEventListener("click", e => { if (e.target === el.modal) { el.modalSave.style.display = ""; closeDialog(); } });

  // Comments modal events
  el.commentsModalClose.addEventListener("click", closeCommentsDialog);
  el.commentsModalDone.addEventListener("click", closeCommentsDialog);
  el.commentsModal.addEventListener("click", e => { if (e.target === el.commentsModal) closeCommentsDialog(); });
}

// ── Workstation autosave ──────────────────────────────────────────────────────
// Creator Nexus has no database: channels, policy rules, upload cards and the
// marketing queue all live in browser localStorage. That made one bad page load
// enough to lose the lot. Every write is now mirrored to the workstation, and a
// browser that comes up empty pulls the copy back on its own.
//
// Backend: bp_creator_nexus.py on :5000 — keeps a rotating history and refuses to
// let an empty channel list replace a populated one.

const CN_SYNC_URL       = `${API_BASE}/api/creator-nexus/state`;
const CN_SYNC_KEYS      = [STORAGE_KEY, "creator_nexus_channels_v1", ADSENSE_KEY,
                           UPLOAD_KEY, MKT_KEY, MKT_LOG_KEY];
const CN_SYNC_DEBOUNCE  = 1500;        // ms of quiet after the last change
const CN_SYNC_HEARTBEAT = 5 * 60000;   // catches edits made outside a save function

let _cnBootPending = true;   // no uploads until the restore check has answered
let _cnSyncTimer   = null;
let _cnLastPayload = "";
let _cnSyncing     = false;

function _cnCollectKeys() {
  const keys = {};
  CN_SYNC_KEYS.forEach(k => {
    const v = localStorage.getItem(k);
    if (v !== null) keys[k] = v;
  });
  return keys;
}

// The "Sample Channel" placeholder must never reach the server — it would look
// like a legitimate 1-channel state and quietly replace the real registry.
function _cnIsDemoOnly() {
  return state.channels.length === 1 && state.channels[0].__demoSeed === true;
}

function _cnScheduleSync() {
  if (_cnBootPending || _cnIsDemoOnly()) return;
  clearTimeout(_cnSyncTimer);
  _cnSyncTimer = setTimeout(_cnSyncNow, CN_SYNC_DEBOUNCE);
}

async function _cnSyncNow() {
  if (_cnSyncing) { _cnScheduleSync(); return; }
  const payload = JSON.stringify({ keys: _cnCollectKeys() });
  if (payload === _cnLastPayload) return;   // nothing actually changed
  _cnSyncing = true;
  try {
    const res  = await fetch(CN_SYNC_URL, {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    payload,
    });
    const data = await res.json();
    if (data.success) {
      _cnLastPayload = payload;
    } else if (res.status === 409) {
      console.warn("Creator Nexus autosave REFUSED:", data.error, "|", data.hint);
    } else {
      console.warn("Creator Nexus autosave failed:", data.error);
    }
  } catch (e) {
    console.warn("Creator Nexus autosave unreachable:", e.message);
  } finally {
    _cnSyncing = false;
  }
}

async function _cnBootRestore() {
  const hadLocal = state.channels.length > 0;
  try {
    const res  = await fetch(CN_SYNC_URL, { cache: "no-store" });
    const data = await res.json();
    if (!data.success) return;

    if (hadLocal) {
      if (!data.exists) console.warn("Creator Nexus: no workstation backup exists yet.");
      return;
    }
    if ((data.channel_count || 0) > 0 && data.keys && Object.keys(data.keys).length) {
      // One attempt per tab session — never loop if the restore fails to stick.
      if (sessionStorage.getItem("cn_restore_attempted")) {
        console.warn("Creator Nexus: restore already attempted this session, not reloading again.");
        return;
      }
      sessionStorage.setItem("cn_restore_attempted", "1");
      Object.entries(data.keys).forEach(([k, v]) => localStorage.setItem(k, v));
      console.warn(`Creator Nexus: browser storage was empty — restored ${data.channel_count} ` +
                   `channel(s) from the workstation copy saved ${data.saved_at}.`);
      location.reload();
      return;
    }
  } catch (e) {
    console.warn("Creator Nexus: workstation copy unreachable:", e.message);
  } finally {
    _cnBootPending = false;
  }
}

setInterval(() => { if (!_cnBootPending) _cnSyncNow(); }, CN_SYNC_HEARTBEAT);

// Last edit before the tab closes. text/plain keeps this a simple request —
// a beacon cannot survive a CORS preflight, and the endpoint parses it forced.
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState !== "hidden" || _cnBootPending || _cnIsDemoOnly()) return;
  const payload = JSON.stringify({ keys: _cnCollectKeys() });
  if (payload !== _cnLastPayload && navigator.sendBeacon) {
    navigator.sendBeacon(CN_SYNC_URL, new Blob([payload], { type: "text/plain" }));
  }
});

init();

