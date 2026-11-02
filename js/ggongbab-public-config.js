/* Browser-public values ONLY: the project URL and the publishable key, never a secret key.
 * On main only the tip board loads this file (tip.html, js/ggongbab-tips.js): it calls the checking
 * functions, uploads a tip's photos and reads ggongbab_tip_board (AGENTS.md, docs/GGONGBAB_TIPS.md;
 * owner 2026-11-02). Lab's public feed reads the same values.
 * Empty values close the tip form ("지금은 제보를 받을 수 없어요"); no other page depends on them.
 * No environment-file loading or implicit environment-variable expansion.
 */
window.BABDODUK_PUBLIC_FEED_CONFIG = Object.freeze({
  SUPABASE_URL: 'https://myjglfynhnptlclawlcc.supabase.co',
  SUPABASE_PUBLISHABLE_KEY: 'sb_publishable_oglEnbZKKiKwKmO6LaVxew_SOdjenxF'
});
