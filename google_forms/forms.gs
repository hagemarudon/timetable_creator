/**
 * 塾の時間割作成：希望を集める Google フォーム（Google Apps Script）
 *
 * 使い方（くわしくは google_forms/README.md）
 *   1. 新しい Google スプレッドシートを作り、「拡張機能 → Apps Script」にこのファイルを丸ごと貼る
 *   2. 下の「設定」を塾に合わせて直し、関数「フォームを作る」を実行する
 *      → 生徒用・講師用の2つのフォームができ、回答はこのスプレッドシートに集まる
 *   3. 回答が集まったら、メニュー「時間割 → 回答を入力シートにまとめる」を押す
 *      → アプリの入力と同じ5シート（コマ設定・生徒_受講希望・生徒_空き時間・講師_担当可能科目・講師_空き時間）ができる
 *   4. アプリで、このスプレッドシートのURLを読み込む（または Excel でダウンロードしてアップロード）
 */

// ===== 設定（アプリの条件と合わせる） =====
var CONFIG = {
  juku: '〇〇塾',
  // 関数をエディタから直接実行するときの時間割の種類（メニューから使うときは気にしなくてよい）
  //   '通常授業'：毎週同じ曜日の時間割。空き時間を曜日（days）ごとに聞く
  //   '講習'：冬期・夏期・春期講習など。空き時間を下の season の日付ごとに聞く
  // 回答をまとめるときは、フォームの題名に「講習」が入っていれば講習、入っていなければ通常授業として読む
  kind: '通常授業',
  days: ['月', '火', '水', '木', '金', '土'],
  // 授業のコマ（90分）。「コマ設定」シートになり、アプリはこのコマに授業を入れる（講習期は season.komas を使う）
  komas: [
    { no: 1, start: '16:00', end: '17:30' },
    { no: 2, start: '17:30', end: '19:00' },
    { no: 3, start: '19:00', end: '20:30' },
    { no: 4, start: '20:30', end: '22:00' },
  ],
  // 空き時間の質問の刻み（分）。最初のコマの開始から最後のコマの終了までをこの刻みで聞く。
  // アプリは、コマの時間にかかる枠すべてに○があるとき、そのコマが空いているとみなす
  slotMinutes: 30,
  subjects: ['英語', '数学', '物理', '化学', '国語'],
  grades: ['小4', '小5', '小6', '中1', '中2', '中3', '高1', '高2', '高3'],
  maxTimesPerWeek: 3, // 生徒が1科目で選べる週の回数の上限
  // 講習の期間・休み・コマ（講習のフォームを作る・まとめるときに使う。アプリの講習の設定と同じにする）
  season: {
    name: '冬期講習',
    start: '2026-12-24',
    end: '2027-01-07',
    closedWeekdays: ['日'],
    closedDates: ['2026-12-31', '2027-01-01', '2027-01-02', '2027-01-03'],
    komas: [
      { no: 1, start: '13:00', end: '14:30' },
      { no: 2, start: '14:30', end: '16:00' },
      { no: 3, start: '16:00', end: '17:30' },
      { no: 4, start: '17:30', end: '19:00' },
      { no: 5, start: '19:00', end: '20:30' },
      { no: 6, start: '20:30', end: '22:00' },
    ],
    maxTimes: 10, // 生徒が1科目で選べる講習期間中の回数の上限
    // 空き時間を聞く時間帯（例：'13:00~15:00'）。空 [] なら slotMinutes（30分）ごとに聞く。
    //   全日同じ時間帯：['13:00~15:00', '15:00~17:00', '17:00~19:00', '19:00~22:00']
    //     → 行が時間帯・列が日付の表で聞く
    //   日によって変える：{ '12/24': ['13:00~15:00', '15:00~17:00'], '12/26': ['10:00~12:00'], '*': [ほかの日の時間帯] }
    //     → 「12/24(木) 13:00〜15:00」のような選択肢から選ぶ
    // アプリは、コマ（90分）の時間が○を付けた時間帯にすっかり入るとき、そのコマに授業を入れる
    times: [],
  },
};

// フォームの質問の見出し（回答を読むときにもこの見出しで探す）
var Q = {
  name: '氏名',
  grade: '学年',
  lessons: '受講したい科目と週の回数',
  studentAvail: '通塾できる時間（○を付けたコマに授業を入れます）',
  note: 'その他の要望（任意）',
  teacherSubjects: '担当できる科目',
  teacherForms: '担当できる授業の形式',
  teacherMax: '1週間に担当できる最大コマ数（任意）',
  teacherAvail: '出勤できる時間',
};

// 講習期は質問の見出しを変える（通常期のフォームの回答は Q の見出しのまま読む）
var Q_SEASON = {
  lessons: '受講したい科目と講習の回数',
  studentAvail: '通塾できる日と時間（○を付けたコマに授業を入れます）',
  teacherMax: '講習期間中に担当できる最大コマ数（任意）',
  teacherAvail: '出勤できる日と時間',
};

var NONE = '受けない';
var FORMS = ['集団', '個別'];
var SHEETS = {
  koma: 'コマ設定',
  studentReq: '生徒_受講希望',
  studentAvail: '生徒_空き時間',
  teacher: '講師_担当可能科目',
  teacherAvail: '講師_空き時間',
};
var PROP_STUDENT = 'studentFormId';
var PROP_TEACHER = 'teacherFormId';
var SEASON_WORD = '講習';
// 講習の入力シートは名前に「講習」を入れる（例：講習_生徒_受講希望）。アプリは講習を選んだときだけこのシートを読む
var SEASON_PREFIX = SEASON_WORD + '_';

// ===== メニュー =====
function onOpen() {
  SpreadsheetApp.getUi().createMenu('時間割')
    .addItem('フォームを作る（通常授業）', 'フォームを作る')
    .addItem('フォームを作る（講習）', '講習のフォームを作る')
    .addItem('回答を入力シートにまとめる', '入力シートを作る')
    .addItem('フォームのURLを表示', 'フォームのURLを表示')
    .addSeparator()
    .addItem('新しい期を始める（通常授業。前の回答を使わない）', '新しい期を始める')
    .addItem('新しい講習を始める（前の講習の回答を使わない）', '新しい講習を始める')
    .addToUi();
}

// ===== 新しい期を始める =====
// 学期や講習が変わると生徒・講師も変わるので、前の期の回答を新しい時間割に混ぜないようにする。
// 「新しい期を始める」を押した日時を覚えておき、まとめるときはそれより前に送られた回答を使わない。
// 前の期にまとめたシートの「希望講師（任意）」「固定（任意）」と生徒ID・講師IDも引き継がない。
// 通常授業と講習は別々に区切る（冬期講習を始めても、通常授業の回答はそのまま使う）。
var PROP_TERM = 'termStart';
var PROP_BUILT = 'builtAt';

function 新しい期を始める() {
  startTerm_(false);
}

function 新しい講習を始める() {
  startTerm_(true);
}

function termKey_(prop, season) {
  return prop + (season ? '_season' : '');
}

function startTerm_(season, askFirst) {
  var kind = season ? '講習' : '通常授業';
  if (askFirst !== false && !confirm_('今から新しい' + (season ? '講習' : '期') + 'の回答を集めます。\n'
      + '「回答を入力シートにまとめる」では、今より前に送られた' + kind + 'の回答を使いません'
      + '（前にまとめたシートの希望講師・固定・IDも引き継ぎません）。よろしいですか？')) {
    return false;
  }
  var now = Date.now();
  PropertiesService.getDocumentProperties().setProperty(termKey_(PROP_TERM, season), String(now));
  var msg = kind + '：' + formatTime_(now) + ' より前の回答は、これから使いません。';
  Logger.log(msg);
  try { SpreadsheetApp.getUi().alert(msg); } catch (e) { /* エディタから実行したときはログだけ */ }
  return true;
}

/** 区切りの日時（ミリ秒）より前の回答を外す。{kept: 使う回答, dropped: 外した数}。since が 0 なら全部使う。 */
function termFilter_(responses, since) {
  var kept = (responses || []).filter(function (r) { return !since || r.time >= since; });
  return { kept: kept, dropped: (responses || []).length - kept.length };
}

function formatTime_(ms) {
  try {
    return Utilities.formatDate(new Date(ms), Session.getScriptTimeZone(), 'yyyy/MM/dd HH:mm');
  } catch (e) {
    return new Date(ms).toISOString();
  }
}

// ===== フォームを作る =====
function フォームを作る() {
  makeForms_('通常授業');
}

function 講習のフォームを作る() {
  makeForms_('講習');
}

/** kind（'通常授業' か '講習'）の生徒用・講師用フォームを作る。講習のフォームは題名の最後に「講習」が入る。 */
function makeForms_(kind) {
  CONFIG.kind = kind;
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var props = PropertiesService.getDocumentProperties();
  var suffix = isSeason_(CONFIG) ? '_season' : '';
  if (props.getProperty(PROP_STUDENT + suffix) && !confirm_(kind + 'のフォームはもう作ってあります。新しく作り直しますか？（前のフォームと回答は残ります）')) {
    return;
  }
  var student = makeStudentForm_();
  var teacher = makeTeacherForm_();
  student.setDestination(FormApp.DestinationType.SPREADSHEET, ss.getId());
  teacher.setDestination(FormApp.DestinationType.SPREADSHEET, ss.getId());
  props.setProperty(PROP_STUDENT + suffix, student.getId());
  props.setProperty(PROP_TEACHER + suffix, teacher.getId());
  // 新しいフォームは新しい期のためのことが多いので、前の回答を使わないか聞く
  if (props.getProperty(termKey_(PROP_BUILT, isSeason_(CONFIG)))) {
    startTerm_(isSeason_(CONFIG));
  }
  フォームのURLを表示();
}

function isSeason_(cfg) {
  var kind = (cfg || CONFIG).kind;
  return kind === '講習' || kind === '講習期';
}

/** フォームの題名に「講習」が入っていれば講習のフォーム。 */
function isSeasonTitle_(title) {
  return String(title || '').indexOf(SEASON_WORD) >= 0;
}

/** 種類に合わせた設定（kind だけ変えたもの）。 */
function cfgFor_(season) {
  var out = {};
  Object.keys(CONFIG).forEach(function (k) { out[k] = CONFIG[k]; });
  out.kind = season ? '講習' : '通常授業';
  return out;
}

/** 入力シートの名前（講習は「講習_」を付ける）。 */
function sheetName_(name, season) {
  return (season ? SEASON_PREFIX : '') + name;
}

/** 質問の見出し（講習期は Q_SEASON で上書きしたもの）。 */
function q_(cfg) {
  var out = {};
  Object.keys(Q).forEach(function (k) { out[k] = Q[k]; });
  if (isSeason_(cfg)) Object.keys(Q_SEASON).forEach(function (k) { out[k] = Q_SEASON[k]; });
  return out;
}

/** 空き時間の刻みの説明（時間帯で聞くときは付けない）。 */
function unitNote_() {
  return seasonRanges_(CONFIG) ? '' : '（' + CONFIG.slotMinutes + '分ごと）';
}

/** フォームの題名。講習のフォームは最後に講習の名前（「講習」を含む。例：冬期講習）を付ける。 */
function formTitle_(kind) {
  var title = CONFIG.juku + ' ' + kind;
  if (isSeason_(CONFIG)) {
    var name = CONFIG.season.name || '';
    title += ' ' + (isSeasonTitle_(name) ? name : (name ? name + ' ' : '') + SEASON_WORD);
  }
  return title;
}

function makeStudentForm_() {
  var q = q_(CONFIG);
  var season = isSeason_(CONFIG);
  var form = FormApp.create(formTitle_('受講希望アンケート（生徒用）'));
  form.setDescription('受講したい科目と、通塾できる時間を教えてください。\n'
    + '答え直すときは、送信後に出る「回答を編集」から直すか、同じ氏名でもう一度送ってください（最後の回答を使います）。');
  form.setAllowResponseEdits(true);
  form.addTextItem().setTitle(q.name).setRequired(true);
  form.addListItem().setTitle(q.grade).setChoiceValues(CONFIG.grades).setRequired(true);
  form.addGridItem().setTitle(q.lessons)
    .setHelpText('受けたい科目に、授業の形式（集団・個別）と' + (season ? '講習期間中' : '1週間') + 'の回数を選んでください。'
      + '受けない科目は「' + NONE + '」のままで構いません。')
    .setRows(CONFIG.subjects)
    .setColumns(lessonChoices_());
  addAvailItem_(form, q.studentAvail,
    '通塾できる' + (season ? '日と' : '') + '時間すべてに○を付けてください' + unitNote_() + '。授業は1回'
      + lessonMinutes_() + '分なので、続けて○が付いている時間に入ります。多く付けるほど時間割が組みやすくなります。');
  form.addParagraphTextItem().setTitle(q.note)
    .setHelpText('希望の先生、同じ日に固めたくない、などがあれば書いてください。');
  return form;
}

function makeTeacherForm_() {
  var q = q_(CONFIG);
  var form = FormApp.create(formTitle_('出勤可能日アンケート（講師用）'));
  form.setDescription('担当できる科目と、出勤できる時間を教えてください。答え直すときは同じ氏名でもう一度送ってください（最後の回答を使います）。');
  form.setAllowResponseEdits(true);
  form.addTextItem().setTitle(q.name).setRequired(true);
  form.addCheckboxItem().setTitle(q.teacherSubjects).setChoiceValues(CONFIG.subjects).setRequired(true);
  form.addCheckboxItem().setTitle(q.teacherForms).setChoiceValues(FORMS).setRequired(true);
  form.addTextItem().setTitle(q.teacherMax)
    .setHelpText('上限がなければ空のままで構いません。')
    .setValidation(FormApp.createTextValidation().requireWholeNumber().setHelpText('数字で入力してください').build());
  addAvailItem_(form, q.teacherAvail,
    '出勤できる' + (isSeason_(CONFIG) ? '日と' : '') + '時間すべてに○を付けてください' + unitNote_() + '。');
  return form;
}

function フォームのURLを表示() {
  var props = PropertiesService.getDocumentProperties();
  var lines = [
    ['生徒用（通常授業）', props.getProperty(PROP_STUDENT)], ['講師用（通常授業）', props.getProperty(PROP_TEACHER)],
    ['生徒用（講習）', props.getProperty(PROP_STUDENT + '_season')], ['講師用（講習）', props.getProperty(PROP_TEACHER + '_season')],
  ]
    .filter(function (p) { return p[1]; })
    .map(function (p) {
      var f = FormApp.openById(p[1]);
      return p[0] + '「' + f.getTitle() + '」（回答用、生徒・講師に送るURL）\n' + f.getPublishedUrl() + '\n' + p[0] + '（編集用）\n' + f.getEditUrl();
    });
  var msg = lines.length ? lines.join('\n\n') : 'まだフォームがありません。メニュー「時間割 → フォームを作る」を押してください。';
  Logger.log(msg);
  try { SpreadsheetApp.getUi().alert(msg); } catch (e) { /* エディタから実行したときはログだけ */ }
}

// ===== 回答を入力シートにまとめる =====

/**
 * このスプレッドシートに回答が届くフォーム（とメニューで作ったフォーム）を集める。
 * 題名に「講習」が入っていれば講習、講師のフォームかどうかは題名の「講師」か「担当できる科目」の質問で見分ける。
 */
function linkedForms_(ss) {
  var props = PropertiesService.getDocumentProperties();
  var ids = {};
  [PROP_STUDENT, PROP_TEACHER, PROP_STUDENT + '_season', PROP_TEACHER + '_season'].forEach(function (k) {
    var id = props.getProperty(k);
    if (id) ids[id] = true;
  });
  ss.getSheets().forEach(function (sh) {
    var url = sh.getFormUrl && sh.getFormUrl();
    if (!url) return;
    try { ids[FormApp.openByUrl(url).getId()] = true; } catch (e) { /* 消したフォーム */ }
  });
  return Object.keys(ids).map(function (id) {
    var form = FormApp.openById(id);
    var title = form.getTitle();
    var teacher = title.indexOf('講師') >= 0 || form.getItems().some(function (it) {
      return it.getTitle() === Q.teacherSubjects;
    });
    return { form: form, title: title, season: isSeasonTitle_(title), teacher: teacher };
  });
}

function 入力シートを作る() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var forms = linkedForms_(ss);
  if (!forms.length) {
    throw new Error('フォームがまだありません。先に「フォームを作る」を実行するか、フォームの回答先をこのスプレッドシートにしてください。');
  }
  var props = PropertiesService.getDocumentProperties();
  var msgs = [];
  var warnings = [];
  [false, true].forEach(function (season) {
    var mine = forms.filter(function (f) { return f.season === season; });
    if (!mine.length) return;
    var cfg = cfgFor_(season);
    // 「新しい期を始める」より前の回答は使わない。前の期にまとめたシートからも引き継がない
    var since = Number(props.getProperty(termKey_(PROP_TERM, season)) || 0);
    var builtAt = Number(props.getProperty(termKey_(PROP_BUILT, season)) || 0);
    var samePeriod = !since || builtAt >= since;
    var dropped = 0;
    var responses = function (teacher) {
      var all = mine.filter(function (f) { return f.teacher === teacher; })
        .reduce(function (acc, f) { return acc.concat(readResponses_(f.form)); }, []);
      var t = termFilter_(all, since);
      dropped += t.dropped;
      return t.kept;
    };
    var previous = function (name) { return samePeriod ? readSheet_(ss, sheetName_(name, season)) : []; };
    var students = buildStudentSheets(responses(false), cfg, previous(SHEETS.studentReq));
    var teachers = buildTeacherSheets(responses(true), cfg, previous(SHEETS.teacher));
    writeSheet_(ss, sheetName_(SHEETS.koma, season), komaSheet(cfg));
    writeSheet_(ss, sheetName_(SHEETS.studentReq, season), students.requests);
    writeSheet_(ss, sheetName_(SHEETS.studentAvail, season), students.avail);
    writeSheet_(ss, sheetName_(SHEETS.teacher, season), teachers.teachers);
    writeSheet_(ss, sheetName_(SHEETS.teacherAvail, season), teachers.avail);
    props.setProperty(termKey_(PROP_BUILT, season), String(Date.now()));
    var kind = season ? '講習' : '通常授業';
    msgs.push(kind + '（' + mine.map(function (f) { return '「' + f.title + '」'; }).join('・') + '）：生徒 '
      + (students.avail.length - 1) + '人・講師 ' + (teachers.avail.length - 1) + '人'
      + (since ? '。' + formatTime_(since) + ' 以降の回答だけを使いました'
        + (dropped ? '（それより前の ' + dropped + ' 件は使っていません）' : '') : '')
      + (season ? '。シート名の頭に「' + SEASON_PREFIX + '」を付けました' : ''));
    students.warnings.concat(teachers.warnings).forEach(function (w) { warnings.push(kind + '：' + w); });
  });

  var msg = '回答をまとめました。\n' + msgs.join('\n') + '\nアプリでこのスプレッドシートを読み込み、ホームで通常授業か講習を選んでください。';
  if (warnings.length) msg += '\n\n確認してください：\n' + warnings.join('\n');
  Logger.log(msg);
  try { SpreadsheetApp.getUi().alert(msg); } catch (e) { /* エディタから実行したときはログだけ */ }
}

/**
 * フォームの回答を {time, answers: {見出し: 回答}} の配列にする（古い順）。
 * グリッドの質問は、回答の配列に加えて行の見出しも answers['<見出し>#rows'] に入れる
 * （フォームの行を手で直していても、見出しの時刻で読めるようにするため）。
 * 質問の見出しを手で変えたフォームでも読めるよう、最初の記述式の回答を answers['#name']、
 * 最初のチェックボックスのグリッドの回答を answers['#avail']（行の見出しは '#avail#rows'）にも入れる。
 */
function readResponses_(form) {
  var rows = {};
  var firstGrid = null;
  form.getItems(FormApp.ItemType.CHECKBOX_GRID).forEach(function (it) {
    rows[it.getTitle()] = it.asCheckboxGridItem().getRows();
    if (firstGrid === null) firstGrid = it.getTitle();
  });
  var firstText = (form.getItems(FormApp.ItemType.TEXT)[0] || { getTitle: function () { return null; } }).getTitle();
  return form.getResponses().map(function (r) {
    var answers = {};
    r.getItemResponses().forEach(function (ir) {
      var title = ir.getItem().getTitle();
      answers[title] = ir.getResponse();
      if (rows[title]) answers[title + '#rows'] = rows[title];
      if (title === firstText) answers['#name'] = answers[title];
      if (title === firstGrid) {
        answers['#avail'] = answers[title];
        answers['#avail#rows'] = rows[title];
      }
    });
    return { time: r.getTimestamp().getTime(), answers: answers };
  });
}

function readSheet_(ss, name) {
  var sh = ss.getSheetByName(name);
  return sh && sh.getLastRow() > 0 ? sh.getDataRange().getDisplayValues() : [];
}

function writeSheet_(ss, name, rows) {
  var sh = ss.getSheetByName(name) || ss.insertSheet(name);
  sh.clear();
  var width = rows[0].length;
  var range = sh.getRange(1, 1, rows.length, width);
  range.setNumberFormat('@'); // 「月16:00」や IDを文字のまま入れる
  range.setValues(rows.map(function (r) { return r.map(function (v) { return v == null ? '' : String(v); }); }));
  sh.setFrozenRows(1);
}

function confirm_(msg) {
  var ui = SpreadsheetApp.getUi();
  return ui.alert(msg, ui.ButtonSet.YES_NO) === ui.Button.YES;
}

// ===== ここから下は回答を表にする処理（Apps Script 以外でも動く） =====

/** コマ割（講習期は season.komas）。 */
function komas_(cfg) {
  cfg = cfg || CONFIG;
  return isSeason_(cfg) && cfg.season.komas ? cfg.season.komas : cfg.komas;
}

/**
 * 空き時間を聞く日。通常期は曜日（月, 火, …）、講習期は期間の日付から休みを除いた「12/24(木)」の形
 * （アプリの講習期の空き時間の列「12/24(木)16:00」と同じ書き方）。
 */
function days_(cfg) {
  cfg = cfg || CONFIG;
  if (!isSeason_(cfg)) return cfg.days;
  var s = cfg.season;
  var W = ['日', '月', '火', '水', '木', '金', '土'];
  var closed = {};
  (s.closedDates || []).forEach(function (d) { closed[d] = true; });
  var ymd = function (text) { var p = String(text).split('-').map(Number); return new Date(p[0], p[1] - 1, p[2]); };
  var pad = function (n) { return (n < 10 ? '0' : '') + n; };
  var out = [];
  for (var d = ymd(s.start), end = ymd(s.end); d <= end; d.setDate(d.getDate() + 1)) {
    var iso = d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
    var wd = W[d.getDay()];
    if ((s.closedWeekdays || []).indexOf(wd) >= 0 || closed[iso]) continue;
    out.push((d.getMonth() + 1) + '/' + d.getDate() + '(' + wd + ')');
  }
  return out;
}

function komaLabels_(cfg) {
  cfg = cfg || CONFIG;
  return komas_(cfg).map(function (k) { return k.no + '限 ' + k.start + '〜' + k.end; });
}

/** 受講の選択肢。通常期は「個別 週2回」、講習期は講習期間全体の回数で「個別 6回」。 */
function lessonChoices_(cfg) {
  cfg = cfg || CONFIG;
  var season = isSeason_(cfg);
  var max = season ? cfg.season.maxTimes || 10 : cfg.maxTimesPerWeek;
  var out = [NONE];
  FORMS.forEach(function (f) {
    for (var n = 1; n <= max; n++) out.push(f + (season ? ' ' : ' 週') + n + '回');
  });
  return out;
}

function toMin_(hhmm) {
  var m = String(hhmm).match(/(\d{1,2}):(\d{2})/);
  return m ? Number(m[1]) * 60 + Number(m[2]) : null;
}

function toHhmm_(min) {
  var m = String(min % 60);
  return Math.floor(min / 60) + ':' + (m.length < 2 ? '0' + m : m);
}

function lessonMinutes_(cfg) {
  cfg = cfg || CONFIG;
  var k = komas_(cfg)[0];
  return toMin_(k.end) - toMin_(k.start);
}

/** 空き時間の枠の開始（分）。最初のコマの開始から最後のコマの終了まで、slotMinutes 刻み。 */
function cellStarts_(cfg) {
  cfg = cfg || CONFIG;
  var first = Math.min.apply(null, komas_(cfg).map(function (k) { return toMin_(k.start); }));
  var last = Math.max.apply(null, komas_(cfg).map(function (k) { return toMin_(k.end); }));
  var out = [];
  for (var t = first; t < last; t += cfg.slotMinutes) out.push(t);
  return out;
}

/** フォームの空き時間の行の見出し（例：16:00〜16:30）。 */
function cellLabels_(cfg) {
  cfg = cfg || CONFIG;
  return cellStarts_(cfg).map(function (t) { return toHhmm_(t) + '〜' + toHhmm_(t + cfg.slotMinutes); });
}

/** 「13:00~15:00」を [780, 900]（分）にする。読めなければ null。 */
function parseRange_(text) {
  var m = String(text).match(/(\d{1,2})[:：](\d{2})\s*[~〜～\-－–]\s*(\d{1,2})[:：](\d{2})/);
  return m ? [Number(m[1]) * 60 + Number(m[2]), Number(m[3]) * 60 + Number(m[4])] : null;
}

function rangeLabel_(r) {
  return toHhmm_(r[0]) + '〜' + toHhmm_(r[1]);
}

/**
 * 講習期に時間帯（season.times）で聞くときの、日ごとの時間帯 [{day: '12/24(木)', ranges: [[780, 900], …]}]。
 * 時間帯を使わない（30分ごとに聞く）ときは null。
 */
function seasonRanges_(cfg) {
  cfg = cfg || CONFIG;
  var t = isSeason_(cfg) ? cfg.season.times : null;
  if (!t || (Array.isArray(t) && !t.length)) return null;
  return days_(cfg).map(function (d) {
    var list = Array.isArray(t) ? t : (t[d.replace(/\(.*$/, '')] || t[d] || t['*'] || []);
    return { day: d, ranges: list.map(parseRange_).filter(Boolean) };
  });
}

/** 日によって時間帯が違う（選択肢から選ぶ形で聞く）か。 */
function rangesPerDay_(cfg) {
  cfg = cfg || CONFIG;
  return !!seasonRanges_(cfg) && !Array.isArray(cfg.season.times);
}

/** 空き時間の行の見出し。時間帯で聞くとき（全日同じ）は「13:00〜15:00」、それ以外は30分の枠。 */
function availRows_(cfg) {
  cfg = cfg || CONFIG;
  if (!seasonRanges_(cfg)) return cellLabels_(cfg);
  return rangesPerDay_(cfg) ? [] : cfg.season.times.map(parseRange_).filter(Boolean).map(rangeLabel_);
}

/** 日によって時間帯が違うときの選択肢（例：12/24(木) 13:00〜15:00）。 */
function availChoices_(cfg) {
  var out = [];
  seasonRanges_(cfg).forEach(function (x) {
    x.ranges.forEach(function (r) { out.push(x.day + ' ' + rangeLabel_(r)); });
  });
  return out;
}

/** 空き時間の質問を作る（30分ごと・時間帯の表・日ごとの時間帯の選択肢）。 */
function addAvailItem_(form, title, help) {
  if (rangesPerDay_(CONFIG)) {
    return form.addCheckboxItem().setTitle(title).setHelpText(help).setChoiceValues(availChoices_(CONFIG));
  }
  return form.addCheckboxGridItem().setTitle(title).setHelpText(help).setRows(availRows_()).setColumns(days_());
}

/**
 * 空き時間シートの列（例：月16:00、講習期は 12/24(木)16:00）。
 * 講習期を時間帯で聞くときは時間帯の列（例：12/24(木)13:00〜15:00）。アプリはどちらも読める。
 */
function slotLabels_(cfg) {
  var out = [];
  var ranges = seasonRanges_(cfg);
  if (ranges) {
    ranges.forEach(function (x) { x.ranges.forEach(function (r) { out.push(x.day + rangeLabel_(r)); }); });
    return out;
  }
  days_(cfg).forEach(function (d) { cellStarts_(cfg).forEach(function (t) { out.push(d + toHhmm_(t)); }); });
  return out;
}

/** 氏名の空白（全角も）を除いて、同じ人の回答をまとめるためのキーにする。 */
function nameKey_(name) {
  return String(name || '').replace(/[\s　]+/g, '');
}

/** 同じ氏名の回答は最後のものだけ残す（最初に回答した順に並べる）。 */
/** 回答の氏名（見出しが「氏名」でなければ、最初の記述式の回答）。 */
function nameOf_(answers) {
  return answers[Q.name] != null ? answers[Q.name] : answers['#name'];
}

/** 回答の空き時間 [回答, 行の見出し]（見出しが違えば、最初のチェックボックスのグリッド）。 */
function availOf_(answers, title) {
  return answers[title] != null ? [answers[title], answers[title + '#rows']] : [answers['#avail'], answers['#avail#rows']];
}

function latestByName_(responses) {
  var order = [];
  var latest = {};
  responses.slice().sort(function (a, b) { return a.time - b.time; }).forEach(function (r) {
    var key = nameKey_(nameOf_(r.answers));
    if (!key) return;
    if (!(key in latest)) order.push(key);
    latest[key] = r;
  });
  return order.map(function (k) { return latest[k]; });
}

/**
 * 空き時間の回答を、空き時間シートの列名（「月16:00」、講習期は「12/24(木)16:00」）の集合にする。
 * 表（行=時間の枠, 列=曜日・日付）は、rows（フォームの行の見出し）があれば見出しの時刻で、無ければ行の順番で枠を決める。
 * 講習期を時間帯で聞くときは「12/24(木)13:00〜15:00」の集合にする（日ごとの選択肢の回答も読む）。
 */
/**
 * フォームの列の日（例：「12/20 日」「12/20(日)」）を、空き時間シートの列の日（days_ の「12/20(日)」）にそろえる。
 * フォームの見出しを手で直していても、月/日が同じなら同じ日として読む。
 */
function dayOf_(text, cfg) {
  var m = String(text).match(/(\d{1,2})\/(\d{1,2})/);
  if (!m || !isSeason_(cfg)) return String(text).trim();
  var key = Number(m[1]) + '/' + Number(m[2]);
  var hit = days_(cfg).filter(function (d) { return d.replace(/\(.*$/, '') === key; })[0];
  return hit || String(text).trim();
}

function availSet_(grid, cfg, rows) {
  var set = {};
  if (seasonRanges_(cfg)) {
    var defaults = availRows_(cfg);
    (grid || []).forEach(function (item, i) {
      if (!item) return;
      if (rangesPerDay_(cfg)) {
        // 選択肢「12/24(木) 13:00〜15:00」
        var m = String(item).match(/^\s*(.*?)\s*(\d{1,2}[:：]\d{2}\s*[~〜～\-－–]\s*\d{1,2}[:：]\d{2})/);
        var r = m && parseRange_(m[2]);
        if (r) set[dayOf_(m[1], cfg) + rangeLabel_(r)] = true;
        return;
      }
      // 表（行=時間帯, 列=日付）
      var range = parseRange_(rows && rows[i] != null ? rows[i] : defaults[i]);
      if (!range) return;
      (Array.isArray(item) ? item : [item]).forEach(function (d) { if (d) set[dayOf_(d, cfg) + rangeLabel_(range)] = true; });
    });
    return set;
  }
  var starts = cellStarts_(cfg);
  (grid || []).forEach(function (cols, i) {
    var t = rows && rows[i] != null ? toMin_(rows[i]) : starts[i];
    if (t == null || !cols) return;
    (Array.isArray(cols) ? cols : [cols]).forEach(function (d) { if (d) set[dayOf_(d, cfg) + toHhmm_(t)] = true; });
  });
  return set;
}

/** 前回まとめたシートから「氏名 → ID」と、手で足した列の値を読む。 */
function previousIds_(rows, idCol) {
  var ids = {};
  var extra = {};
  var max = 0;
  if (rows && rows.length > 1) {
    var h = rows[0];
    var iId = h.indexOf(idCol), iName = h.indexOf('氏名'), iSubj = h.indexOf('科目');
    rows.slice(1).forEach(function (r) {
      var key = nameKey_(r[iName]);
      var id = String(r[iId] || '');
      if (!key || !id) return;
      ids[key] = id;
      var m = id.match(/(\d+)$/);
      if (m) max = Math.max(max, Number(m[1]));
      if (iSubj >= 0) {
        var keep = {};
        h.forEach(function (col, j) { if (/（任意）$/.test(col) && r[j]) keep[col] = r[j]; });
        extra[key + '\t' + r[iSubj]] = keep;
      }
    });
  }
  return { ids: ids, extra: extra, next: max + 1 };
}

function idFor_(prev, prefix, key) {
  if (!prev.ids[key]) {
    var n = String(prev.next++);
    while (n.length < 3) n = '0' + n;
    prev.ids[key] = prefix + n;
  }
  return prev.ids[key];
}

function komaSheet(cfg) {
  return [['コマ', '開始', '終了']].concat(komas_(cfg).map(function (k) { return [k.no, k.start, k.end]; }));
}

/**
 * 生徒用フォームの回答から「生徒_受講希望」「生徒_空き時間」の表を作る。
 * previous には前回まとめた「生徒_受講希望」を渡す（同じ氏名には同じ生徒IDを使い、希望講師・固定の列を引き継ぐ）。
 */
function buildStudentSheets(responses, cfg, previous) {
  var prev = previousIds_(previous, '生徒ID');
  var slots = slotLabels_(cfg);
  var Q = q_(cfg);
  var requests = [['生徒ID', '氏名', '学年', '科目', '形式', isSeason_(cfg) ? '回数' : '週の回数',
    '希望講師（任意）', '固定（任意）', '要望']];
  var avail = [['生徒ID', '氏名'].concat(slots)];
  var warnings = [];
  latestByName_(responses).forEach(function (r) {
    var a = r.answers;
    var key = nameKey_(nameOf_(a));
    var name = String(nameOf_(a)).trim();
    var id = idFor_(prev, 'S', key);
    var lessons = a[Q.lessons] || [];
    var count = 0;
    cfg.subjects.forEach(function (subj, i) {
      var m = String(lessons[i] || '').match(/^(集団|個別) (?:週)?(\d+)回$/);
      if (!m) return;
      var keep = prev.extra[key + '\t' + subj] || {};
      requests.push([id, name, a[Q.grade] || '', subj, m[1], m[2],
        keep['希望講師（任意）'] || '', keep['固定（任意）'] || '', count === 0 ? (a[Q.note] || '') : '']);
      count++;
    });
    var av = availOf_(a, Q.studentAvail);
    var set = availSet_(av[0], cfg, av[1]);
    avail.push([id, name].concat(slots.map(function (s) { return set[s] ? '○' : ''; })));
    if (!count) warnings.push('生徒 ' + name + '：受講したい科目が選ばれていません。');
    if (!Object.keys(set).length) warnings.push('生徒 ' + name + '：通塾できる時間が選ばれていません。');
  });
  return { requests: requests, avail: avail, warnings: warnings };
}

/**
 * 講師用フォームの回答から「講師_担当可能科目」「講師_空き時間」の表を作る。
 * previous には前回まとめた「講師_担当可能科目」を渡す（同じ氏名には同じ講師IDを使う）。
 */
function buildTeacherSheets(responses, cfg, previous) {
  var prev = previousIds_(previous, '講師ID');
  var slots = slotLabels_(cfg);
  var Q = q_(cfg);
  var teachers = [['講師ID', '氏名'].concat(cfg.subjects, ['集団可', '個別可', isSeason_(cfg) ? '上限コマ' : '週の上限コマ'])];
  var avail = [['講師ID', '氏名'].concat(slots)];
  var warnings = [];
  latestByName_(responses).forEach(function (r) {
    var a = r.answers;
    var name = String(nameOf_(a)).trim();
    var id = idFor_(prev, 'T', nameKey_(nameOf_(a)));
    var subjects = [].concat(a[Q.teacherSubjects] || []);
    var forms = [].concat(a[Q.teacherForms] || []);
    var max = String(a[Q.teacherMax] || '').trim();
    teachers.push([id, name]
      .concat(cfg.subjects.map(function (s) { return subjects.indexOf(s) >= 0 ? '○' : ''; }))
      .concat([forms.indexOf('集団') >= 0 ? '○' : '', forms.indexOf('個別') >= 0 ? '○' : '', max]));
    var av = availOf_(a, Q.teacherAvail);
    var set = availSet_(av[0], cfg, av[1]);
    avail.push([id, name].concat(slots.map(function (s) { return set[s] ? '○' : ''; })));
    if (!Object.keys(set).length) warnings.push('講師 ' + name + '：出勤できる時間が選ばれていません。');
  });
  return { teachers: teachers, avail: avail, warnings: warnings };
}

// テスト用（Apps Script では module が無いので何もしない）
if (typeof module !== 'undefined') {
  module.exports = {
    CONFIG: CONFIG, Q: Q, komaSheet: komaSheet, lessonChoices_: lessonChoices_, komaLabels_: komaLabels_,
    cellLabels_: cellLabels_, days_: days_, q_: q_, cfgFor_: cfgFor_, formTitle_: formTitle_, sheetName_: sheetName_,
    isSeasonTitle_: isSeasonTitle_, termFilter_: termFilter_, availRows_: availRows_, availChoices_: availChoices_,
    buildStudentSheets: buildStudentSheets, buildTeacherSheets: buildTeacherSheets,
  };
}
