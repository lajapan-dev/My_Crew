/**
 * 右腕AI（LINE × Claude）
 *
 * 社員がLINE公式アカウントに送った質問に、応答ルール（Googleドキュメント）に沿って
 * Claude が本間さんの代わりに答える仕組み。
 *
 * - 設置方法は「設置手順.md」を参照。
 * - APIキーなどの秘密の値は、すべて「スクリプト プロパティ」に入れる。このコードには書かない。
 * - 答え方を変えたいときは、このコードではなく Googleドキュメント（応答ルール）を直す。
 */

// ===== 調整してよい設定 =====
const MODEL = 'claude-opus-5-5';
const EFFORT = 'low';          // LINEの短い質疑なので、速さ重視
const NIGHT_START_HOUR = 22;   // この時刻〜翌朝 NIGHT_END_HOUR 時までは「夜間」
const NIGHT_END_HOUR = 7;
const HISTORY_TURNS = 6;       // 社員ごとに、直近何往復を覚えておくか
const TZ = 'Asia/Tokyo';

// ===== ここから下は、通常さわらない =====
const LOG_SHEET = '応答ログ';
const STAFF_SHEET = '社員名簿';
const LOG_HEADERS = ['日時', '社員名', 'LINEユーザーID', '質問', 'AIの回答', '本人判断', '緊急度', '本人向け要約', '分類'];
const STAFF_HEADERS = ['LINEユーザーID', '名前', '登録日'];

// Claude に返してもらう答えの形
const REPLY_SCHEMA = {
  type: 'object',
  properties: {
    reply: { type: 'string', description: '社員に返すLINEの本文' },
    needs_owner: { type: 'boolean', description: '本間さんの判断が必要なら true' },
    urgency: { type: 'string', enum: ['通常', '今日中', '緊急'] },
    owner_summary: { type: 'string', description: '本間さん向けの1〜2行の要約と、AIの推奨案。不要なら空文字' },
    category: { type: 'string', description: '質問の分類（例：Shopee在庫、クレーム、AI研修、優先順位、その他）' },
  },
  required: ['reply', 'needs_owner', 'urgency', 'owner_summary', 'category'],
  additionalProperties: false,
};

// ---------------------------------------------------------------
// LINE から呼ばれる入口
// ---------------------------------------------------------------
function doPost(e) {
  const body = JSON.parse(e.postData.contents);
  (body.events || []).forEach(function (ev) {
    try {
      handleEvent_(ev);
    } catch (err) {
      notifyOwnerOfError_(err, ev);
    }
  });
  return ContentService.createTextOutput('OK');
}

function handleEvent_(ev) {
  if (ev.type !== 'message') return;
  if (!ev.source || ev.source.type !== 'user') return; // グループトークは次の段階

  // 同じ通知が二重に届いたときは無視する
  const cache = CacheService.getScriptCache();
  if (ev.webhookEventId) {
    if (cache.get('ev:' + ev.webhookEventId)) return;
    cache.put('ev:' + ev.webhookEventId, '1', 600);
  }

  const userId = ev.source.userId;
  const staff = findStaff_(userId);

  if (ev.message.type !== 'text') {
    if (staff) {
      replyLine_(ev.replyToken, 'いまは文字の質問にだけ答えられます。写真やスタンプの内容は、文章で送ってください。');
    }
    return;
  }

  const text = ev.message.text.trim();
  if (!staff) {
    handleRegistration_(ev.replyToken, userId, text);
    return;
  }

  answerStaff_(ev.replyToken, userId, staff.name, text);
}

// ---------------------------------------------------------------
// 社員の登録（合言葉を送った人だけが使える）
// ---------------------------------------------------------------
function handleRegistration_(replyToken, userId, text) {
  if (text !== prop_('PASSPHRASE')) {
    replyLine_(replyToken, 'このアカウントは社員専用です。利用するには、社内で共有されている合言葉を送ってください。');
    return;
  }
  const name = getLineDisplayName_(userId) || '名前未取得';
  sheet_(STAFF_SHEET, STAFF_HEADERS).appendRow([userId, name, new Date()]);
  replyLine_(replyToken,
    name + 'さん、登録しました。\n' +
    'ここは本間さんの「右腕AI」です。仕事の質問を送ってください。本間さんの判断基準に沿ってすぐ答えます。\n' +
    '本間さんの判断が必要なものは、こちらから本間さんに伝えます。');
}

// ---------------------------------------------------------------
// 質問に答える
// ---------------------------------------------------------------
function answerStaff_(replyToken, userId, staffName, text) {
  const now = new Date();
  const offHours = isOffHours_(now);
  const header = '[受信 ' + Utilities.formatDate(now, TZ, 'yyyy-MM-dd HH:mm') + ' ' + weekdayJa_(now) +
    '／' + (offHours ? '夜間・休日' : '営業時間内') + '／送信者：' + staffName + ']';
  const userContent = header + '\n' + text;

  const history = loadHistory_(userId);
  const messages = history.concat([{ role: 'user', content: userContent }]);

  let result;
  try {
    result = callClaude_(loadRules_(), messages);
  } catch (err) {
    replyLine_(replyToken, 'ただいまAIが応答できません。急ぎの場合は、本間さんに直接連絡してください。');
    throw err;
  }

  if (!result) {
    // AIが回答を見送った場合
    result = {
      reply: 'この質問にはAIがうまく答えられませんでした。本間さんに伝えておきます。',
      needs_owner: true,
      urgency: '通常',
      owner_summary: 'AIが回答を見送った質問です。内容を確認してください。',
      category: 'その他',
    };
  }

  replyLine_(replyToken, result.reply);
  saveHistory_(userId, history, userContent, result.reply);
  sheet_(LOG_SHEET, LOG_HEADERS).appendRow([
    now, staffName, userId, text, result.reply,
    result.needs_owner ? '要' : '', result.urgency, result.owner_summary, result.category,
  ]);

  if (result.needs_owner) notifyOwner_(staffName, text, result, offHours);
}

// 本間さんへの知らせ方：緊急は即時、今日中は営業時間内なら即時、それ以外は朝のまとめで
function notifyOwner_(staffName, text, result, offHours) {
  const immediate = result.urgency === '緊急' || (result.urgency === '今日中' && !offHours);
  if (!immediate) return;

  const subject = '【右腕AI】【' + result.urgency + '】' + staffName + 'さんから：' + result.category;
  const body =
    '要約：' + result.owner_summary + '\n\n' +
    '社員の質問：\n' + text + '\n\n' +
    'AIが社員に返した内容：\n' + result.reply + '\n';
  MailApp.sendEmail(prop_('OWNER_EMAIL'), subject, body);

  const ownerLineId = props_().getProperty('OWNER_LINE_USER_ID');
  if (result.urgency === '緊急' && ownerLineId) {
    pushLine_(ownerLineId, '【緊急】' + staffName + 'さんから\n' + result.owner_summary);
  }
}

// ---------------------------------------------------------------
// 朝のまとめ（時間トリガーで毎朝1回動かす）
// ---------------------------------------------------------------
function sendMorningDigest() {
  const values = sheet_(LOG_SHEET, LOG_HEADERS).getDataRange().getValues().slice(1);
  const since = new Date(Date.now() - 24 * 60 * 60 * 1000);
  const rows = values.filter(function (r) { return r[0] instanceof Date && r[0] >= since; });
  if (rows.length === 0) return;

  const ownerRows = rows.filter(function (r) { return r[5] === '要'; });
  const counts = {};
  rows.forEach(function (r) { counts[r[8]] = (counts[r[8]] || 0) + 1; });

  let body = 'この24時間で、社員から ' + rows.length + ' 件の質問があり、AIがすべてに返信しました。\n\n';
  body += '■ 本間さんの判断が必要なもの：' + ownerRows.length + ' 件\n';
  ownerRows.forEach(function (r, i) {
    body += '\n' + (i + 1) + '. 【' + r[6] + '】' + r[1] + 'さん（' +
      Utilities.formatDate(r[0], TZ, 'M/d HH:mm') + '）\n' +
      '   要約：' + r[7] + '\n' +
      '   質問：' + r[3] + '\n';
  });
  body += '\n■ 質問の分類\n';
  Object.keys(counts).forEach(function (k) { body += '・' + k + '：' + counts[k] + ' 件\n'; });
  body += '\n全文は応答ログのスプレッドシートで確認できます。変な回答があれば、応答ルールのドキュメントを直してください。\n';

  const subject = '【右腕AI】朝のまとめ ' + Utilities.formatDate(new Date(), TZ, 'M/d') +
    '（本人判断 ' + ownerRows.length + ' 件）';
  MailApp.sendEmail(prop_('OWNER_EMAIL'), subject, body);
}

// ---------------------------------------------------------------
// Claude を呼ぶ
// ---------------------------------------------------------------
function callClaude_(rules, messages) {
  const payload = {
    model: MODEL,
    max_tokens: 4000,
    system: [{ type: 'text', text: rules, cache_control: { type: 'ephemeral', ttl: '1h' } }],
    messages: messages,
    output_config: { effort: EFFORT, format: { type: 'json_schema', schema: REPLY_SCHEMA } },
    // まれにAIが回答を断ったとき、別のモデルで自動的にやり直す
    fallbacks: 'default',
  };
  const options = {
    method: 'post',
    contentType: 'application/json',
    headers: {
      'x-api-key': prop_('ANTHROPIC_API_KEY'),
      'anthropic-version': '2026-10-21',
      'anthropic-beta': 'server-side-fallback-2026-07-01',
    },
    payload: JSON.stringify(payload),
    muteHttpExceptions: true,
  };

  let res;
  for (let attempt = 0; attempt < 2; attempt++) {
    res = UrlFetchApp.fetch('https://api.anthropic.com/v1/messages', options);
    const code = res.getResponseCode();
    if (code === 429 || code >= 500) { Utilities.sleep(2000); continue; } // 混雑時は1回だけ待って再試行
    break;
  }
  if (res.getResponseCode() !== 200) {
    throw new Error('Claude API エラー ' + res.getResponseCode() + '：' + res.getContentText().slice(0, 500));
  }

  const data = JSON.parse(res.getContentText());
  if (data.stop_reason === 'refusal') return null;
  const textBlocks = (data.content || []).filter(function (b) { return b.type === 'text'; });
  if (textBlocks.length === 0) {
    throw new Error('Claudeの応答に本文がありません（stop_reason=' + data.stop_reason + '）');
  }
  return JSON.parse(textBlocks[textBlocks.length - 1].text);
}

// 応答ルール（Googleドキュメント）を読む。10分間は読み直さない
function loadRules_() {
  const cache = CacheService.getScriptCache();
  const cached = cache.get('rules');
  if (cached) return cached;
  const text = DocumentApp.openById(prop_('RULES_DOC_ID')).getBody().getText();
  try { cache.put('rules', text, 600); } catch (e) { /* 長すぎて保存できないときは毎回読む */ }
  return text;
}

// ---------------------------------------------------------------
// 会話の記憶（社員ごとに直近数往復だけ、6時間）
// ---------------------------------------------------------------
function loadHistory_(userId) {
  const raw = CacheService.getScriptCache().get('hist:' + userId);
  return raw ? JSON.parse(raw) : [];
}

function saveHistory_(userId, history, userContent, reply) {
  const updated = history.concat([
    { role: 'user', content: userContent },
    { role: 'assistant', content: reply },
  ]).slice(-HISTORY_TURNS * 2);
  try {
    CacheService.getScriptCache().put('hist:' + userId, JSON.stringify(updated), 21600);
  } catch (e) { /* 記憶できなくても返信は済んでいるので続行 */ }
}

// ---------------------------------------------------------------
// LINE とのやり取り
// ---------------------------------------------------------------
function replyLine_(replyToken, text) {
  lineFetch_('https://api.line.me/v2/bot/message/reply', {
    replyToken: replyToken,
    messages: [{ type: 'text', text: text.slice(0, 4900) }],
  });
}

function pushLine_(to, text) {
  lineFetch_('https://api.line.me/v2/bot/message/push', {
    to: to,
    messages: [{ type: 'text', text: text.slice(0, 4900) }],
  });
}

function lineFetch_(url, payload) {
  const res = UrlFetchApp.fetch(url, {
    method: 'post',
    contentType: 'application/json',
    headers: { Authorization: 'Bearer ' + prop_('LINE_CHANNEL_ACCESS_TOKEN') },
    payload: JSON.stringify(payload),
    muteHttpExceptions: true,
  });
  if (res.getResponseCode() !== 200) {
    throw new Error('LINE送信エラー ' + res.getResponseCode() + '：' + res.getContentText().slice(0, 300));
  }
}

function getLineDisplayName_(userId) {
  const res = UrlFetchApp.fetch('https://api.line.me/v2/bot/profile/' + userId, {
    headers: { Authorization: 'Bearer ' + prop_('LINE_CHANNEL_ACCESS_TOKEN') },
    muteHttpExceptions: true,
  });
  if (res.getResponseCode() !== 200) return null;
  return JSON.parse(res.getContentText()).displayName;
}

// ---------------------------------------------------------------
// 小さな道具
// ---------------------------------------------------------------
function props_() { return PropertiesService.getScriptProperties(); }

function prop_(key) {
  const v = props_().getProperty(key);
  if (!v) throw new Error('スクリプト プロパティ「' + key + '」が未設定です');
  return v;
}

function sheet_(name, headers) {
  const book = SpreadsheetApp.openById(prop_('LOG_SHEET_ID'));
  let sh = book.getSheetByName(name);
  if (!sh) {
    sh = book.insertSheet(name);
    sh.appendRow(headers);
    sh.setFrozenRows(1);
  }
  return sh;
}

function findStaff_(userId) {
  const rows = sheet_(STAFF_SHEET, STAFF_HEADERS).getDataRange().getValues().slice(1);
  for (let i = 0; i < rows.length; i++) {
    if (rows[i][0] === userId) return { name: rows[i][1] };
  }
  return null;
}

function isOffHours_(date) {
  const hour = Number(Utilities.formatDate(date, TZ, 'H'));
  const dow = Number(Utilities.formatDate(date, TZ, 'u')); // 1=月 … 6=土 7=日
  return hour >= NIGHT_START_HOUR || hour < NIGHT_END_HOUR || dow >= 6;
}

function weekdayJa_(date) {
  return '(' + ['月', '火', '水', '木', '金', '土', '日'][Number(Utilities.formatDate(date, TZ, 'u')) - 1] + ')';
}

function notifyOwnerOfError_(err, ev) {
  const email = props_().getProperty('OWNER_EMAIL');
  if (!email) return;
  MailApp.sendEmail(email, '【右腕AI】エラーが起きました',
    String(err && err.stack || err) + '\n\n受信内容：\n' + JSON.stringify(ev).slice(0, 2000));
}

// ---------------------------------------------------------------
// 設置時に1回だけ実行する（権限の許可と、設定漏れのチェック）
// ---------------------------------------------------------------
function setup() {
  ['LINE_CHANNEL_ACCESS_TOKEN', 'ANTHROPIC_API_KEY', 'RULES_DOC_ID', 'LOG_SHEET_ID', 'OWNER_EMAIL', 'PASSPHRASE']
    .forEach(prop_);
  sheet_(LOG_SHEET, LOG_HEADERS);
  sheet_(STAFF_SHEET, STAFF_HEADERS);
  Logger.log('応答ルールの文字数：' + loadRules_().length);
  Logger.log('設定OK。次は testAnswer を実行して、AIの答えを確かめてください。');
}

// LINEを通さずに、AIの答え方だけを試す
function testAnswer() {
  const q = '[受信 テスト／営業時間内／送信者：テスト]\n売れ筋の商品の在庫があと3日分しかありません。どうしたらいいですか？';
  Logger.log(JSON.stringify(callClaude_(loadRules_(), [{ role: 'user', content: q }]), null, 2));
}
