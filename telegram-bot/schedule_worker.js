// Cloudflare Worker: телеграм-бот расписания (24/7, без включённого ПК).
// Telegram шлёт сюда webhook-апдейты; на «расписание»/«/schedule» отвечает слотами выхода
// роликов в вьетнамском и московском времени + сколько до следующего ролика.
//
// Деплой: см. telegram-bot/README.md. Токен бота кладётся в секрет Worker BOT_TOKEN
// (НЕ в код). sendMessage продолжает работать у notify.py параллельно — webhook этому не мешает.

// 2026-07-08: актуализировано под daily.yml/daily-es.yml — EN 5→4 слота (2026-07-01,
// перелив на ES) + 22:13→23:07 (2026-07-05, US prime time); ES 3→4 слота (2026-07-01)
// + 13:17→03:17 (2026-07-07, мексиканский вечерний прайм).
// 2026-07-09: добавлен PT (daily-pt.yml, cron-job.org), слоты 17:23/21:23/23:23/01:23 UTC
// (см. config.py daily_slots_utc).
const EN_SLOTS = [[16, 13], [20, 7], [23, 7], [0, 7]];
// 2026-07-13: слот 16:17 убран (4→3/день, ответ на подавление раздачи ES).
const ES_SLOTS = [[20, 17], [0, 17], [3, 17]];
const PT_SLOTS = [[17, 23], [21, 23], [23, 23], [1, 23]];
const TRIGGERS = ["расписание", "/расписание", "schedule", "/schedule", "/start"];

const pad = (n) => String(n).padStart(2, "0");

// (h,m) UTC → ["HH:MM" Вьетнам(+7), "HH:MM" Москва(+3)]
function conv(h, m) {
  return [`${pad((h + 7) % 24)}:${pad(m)}`, `${pad((h + 3) % 24)}:${pad(m)}`];
}

function buildSchedule() {
  const now = new Date();
  const nowMin = now.getUTCHours() * 60 + now.getUTCMinutes();
  const all = [...new Set([...EN_SLOTS, ...ES_SLOTS, ...PT_SLOTS].map(([h, m]) => h * 60 + m))].sort((a, b) => a - b);

  let next = all.find((s) => s > nowMin);
  let delta;
  if (next === undefined) { next = all[0]; delta = 1440 - nowMin + next; }
  else { delta = next - nowMin; }
  const dh = Math.floor(delta / 60), dm = delta % 60;
  const [nvn, nmsk] = conv(Math.floor(next / 60), next % 60);

  const lines = ["📅 Расписание выхода роликов", "(🇻🇳 Вьетнам · 🇷🇺 Москва)", "", "EN — 4/день:"];
  for (const [h, m] of EN_SLOTS) { const [vn, msk] = conv(h, m); lines.push(`• ${vn} · ${msk}`); }
  lines.push("", "ES — 3/день:");
  for (const [h, m] of ES_SLOTS) { const [vn, msk] = conv(h, m); lines.push(`• ${vn} · ${msk}`); }
  lines.push("", "PT — 4/день:");
  for (const [h, m] of PT_SLOTS) { const [vn, msk] = conv(h, m); lines.push(`• ${vn} · ${msk}`); }
  lines.push("", `⏭ Следующий через ${dh}ч ${pad(dm)}м (в ${nvn} ВН · ${nmsk} МСК)`);
  lines.push("", "ℹ️ Пн–Ср последний слот — серии (Part 1/2/3).", "Вс ~06:00 ВН / 02:00 МСК — лонгформ.");
  return lines.join("\n");
}

export default {
  async fetch(request, env) {
    if (request.method !== "POST") return new Response("schedule-bot ok");
    let update;
    try { update = await request.json(); } catch { return new Response("ok"); }

    const msg = update.message || update.channel_post;
    const text = (msg && msg.text ? msg.text : "").trim().toLowerCase();
    if (msg && TRIGGERS.some((t) => text === t || text.startsWith(t))) {
      await fetch(`https://api.telegram.org/bot${env.BOT_TOKEN}/sendMessage`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ chat_id: msg.chat.id, text: buildSchedule() }),
      });
    }
    return new Response("ok");
  },
};
