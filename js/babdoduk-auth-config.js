/* Optional sign-in (마이 밥도둑, docs/MY_BABDODUK.md). ON since 2026-11-10: the owner turned on Google
 * and kakao under Supabase Authentication (with the redirect URLs) and applied
 * supabase/migrations/011_accounts.sql. Only the hosts listed load the sign-in client; production is not
 * listed, so it never does until a release says so (and my.html answers 404 off babdoduk-lab).
 * No secret belongs here: the project URL and publishable key come from js/ggongbab-public-config.js.
 */
window.BABDODUK_AUTH_CONFIG = Object.freeze({
  enabled: true,
  hosts: Object.freeze(['babdoduk-lab.vercel.app', 'localhost', '127.0.0.1'])
});
