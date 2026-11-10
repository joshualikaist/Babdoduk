/* Optional sign-in (마이 밥도둑, docs/MY_BABDODUK.md). ON since 2026-11-10 on babdoduk-lab, and on
 * production since 2026-11-11 (owner: "로그인은 푸시 및 배포가 안된거임? 이거까지 했어야지"): the owner
 * turned on Google and kakao under Supabase Authentication (with the redirect URLs) and applied
 * supabase/migrations/011_accounts.sql. Only the hosts listed load the sign-in client.
 * No secret belongs here: the project URL and publishable key come from js/ggongbab-public-config.js.
 */
window.BABDODUK_AUTH_CONFIG = Object.freeze({
  enabled: true,
  hosts: Object.freeze(['www.babdodukms.com', 'babdodukms.com', 'babdoduk.vercel.app',
                        'babdoduk-lab.vercel.app', 'localhost', '127.0.0.1'])
});
