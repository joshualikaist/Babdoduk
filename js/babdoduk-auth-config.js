/* Optional sign-in (마이 밥도둑, docs/MY_BABDODUK.md). Off until the owner has
 *   1. turned on Google and kakao under Supabase Authentication (with the redirect URLs), and
 *   2. applied supabase/migrations/011_accounts.sql.
 * Then `enabled` becomes true here, in a normal commit. Only the hosts listed load the sign-in client;
 * production is not listed, so it never does until a release says so.
 * No secret belongs here: the project URL and publishable key come from js/ggongbab-public-config.js.
 */
window.BABDODUK_AUTH_CONFIG = Object.freeze({
  enabled: false,
  hosts: Object.freeze(['babdoduk-lab.vercel.app', 'localhost', '127.0.0.1'])
});
