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
  days: ['月', '火', '水', '木', '金', '土'],
  // 授業のコマ（90分）。「コマ設定」シートになり、アプリはこのコマに授業を入れる
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

// ===== メニュー =====
function onOpen() {
  SpreadsheetApp.getUi().createMenu('時間割')
    .addItem('フォームを作る', 'フォームを作る')
    .addItem('回答を入力シートにまとめる', '入力シートを作る')
    .addItem('フォームのURLを表示', 'フォームのURLを表示')
    .addToUi();
}

// ===== フォームを作る =====
function フォームを作る() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var props = PropertiesService.getDocumentProperties();
  if (props.getProperty(PROP_STUDENT) && !confirm_('フォームはもう作ってあります。新しく作り直しますか？（前のフォームと回答は残ります）')) {
    return;
  }
  var student = makeStudentForm_();
  var teacher = makeTeacherForm_();
  student.setDestination(FormApp.DestinationType.SPREADSHEET, ss.getId());
  teacher.setDestination(FormApp.DestinationType.SPREADSHEET, ss.getId());
  props.setProperty(PROP_STUDENT, student.getId());
  props.setProperty(PROP_TEACHER, teacher.getId());
  フォームのURLを表示();
}

function makeStudentForm_() {
  var form = FormApp.create(CONFIG.juku + ' 受講希望アンケート（生徒用）');
  form.setDescription('受講したい科目と、通塾できる時間を教えてください。\n'
    + '答え直すときは、送信後に出る「回答を編集」から直すか、同じ氏名でもう一度送ってください（最後の回答を使います）。');
  form.setAllowResponseEdits(true);
  form.addTextItem().setTitle(Q.name).setRequired(true);
  form.addListItem().setTitle(Q.grade).setChoiceValues(CONFIG.grades).setRequired(true);
  form.addGridItem().setTitle(Q.lessons)
    .setHelpText('受けたい科目に、授業の形式（集団・個別）と1週間の回数を選んでください。受けない科目は「' + NONE + '」のままで構いません。')
    .setRows(CONFIG.subjects)
    .setColumns(lessonChoices_());
  form.addCheckboxGridItem().setTitle(Q.studentAvail)
    .setHelpText('通塾できる時間すべてに○を付けてください（' + CONFIG.slotMinutes + '分ごと）。授業は1回'
      + lessonMinutes_() + '分なので、続けて○が付いている時間に入ります。多く付けるほど時間割が組みやすくなります。')
    .setRows(cellLabels_())
    .setColumns(CONFIG.days);
  form.addParagraphTextItem().setTitle(Q.note)
    .setHelpText('希望の先生、同じ日に固めたくない、などがあれば書いてください。');
  return form;
}

function makeTeacherForm_() {
  var form = FormApp.create(CONFIG.juku + ' 出勤可能日アンケート（講師用）');
  form.setDescription('担当できる科目と、出勤できる時間を教えてください。答え直すときは同じ氏名でもう一度送ってください（最後の回答を使います）。');
  form.setAllowResponseEdits(true);
  form.addTextItem().setTitle(Q.name).setRequired(true);
  form.addCheckboxItem().setTitle(Q.teacherSubjects).setChoiceValues(CONFIG.subjects).setRequired(true);
  form.addCheckboxItem().setTitle(Q.teacherForms).setChoiceValues(FORMS).setRequired(true);
  form.addTextItem().setTitle(Q.teacherMax)
    .setHelpText('上限がなければ空のままで構いません。')
    .setValidation(FormApp.createTextValidation().requireWholeNumber().setHelpText('数字で入力してください').build());
  form.addCheckboxGridItem().setTitle(Q.teacherAvail)
    .setHelpText('出勤できる時間すべてに○を付けてください（' + CONFIG.slotMinutes + '分ごと）。')
    .setRows(cellLabels_())
    .setColumns(CONFIG.days);
  return form;
}

function フォームのURLを表示() {
  var props = PropertiesService.getDocumentProperties();
  var lines = [['生徒用', props.getProperty(PROP_STUDENT)], ['講師用', props.getProperty(PROP_TEACHER)]]
    .filter(function (p) { return p[1]; })
    .map(function (p) {
      var f = FormApp.openById(p[1]);
      return p[0] + '（回答用、生徒・講師に送るURL）\n' + f.getPublishedUrl() + '\n' + p[0] + '（編集用）\n' + f.getEditUrl();
    });
  var msg = lines.length ? lines.join('\n\n') : 'まだフォームがありません。メニュー「時間割 → フォームを作る」を押してください。';
  Logger.log(msg);
  try { SpreadsheetApp.getUi().alert(msg); } catch (e) { /* エディタから実行したときはログだけ */ }
}

// ===== 回答を入力シートにまとめる =====
function 入力シートを作る() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var props = PropertiesService.getDocumentProperties();
  if (!props.getProperty(PROP_STUDENT)) {
    throw new Error('フォームがまだありません。先に「フォームを作る」を実行してください。');
  }
  var existing = {
    studentReq: readSheet_(ss, SHEETS.studentReq),
    teacher: readSheet_(ss, SHEETS.teacher),
  };
  var students = buildStudentSheets(readResponses_(props.getProperty(PROP_STUDENT)), CONFIG, existing.studentReq);
  var teachers = buildTeacherSheets(readResponses_(props.getProperty(PROP_TEACHER)), CONFIG, existing.teacher);

  writeSheet_(ss, SHEETS.koma, komaSheet(CONFIG));
  writeSheet_(ss, SHEETS.studentReq, students.requests);
  writeSheet_(ss, SHEETS.studentAvail, students.avail);
  writeSheet_(ss, SHEETS.teacher, teachers.teachers);
  writeSheet_(ss, SHEETS.teacherAvail, teachers.avail);

  var msg = '生徒 ' + (students.avail.length - 1) + '人・講師 ' + (teachers.avail.length - 1) + '人の回答をまとめました。\n'
    + 'アプリでこのスプレッドシートのURLを読み込んでください。';
  if (students.warnings.length + teachers.warnings.length) {
    msg += '\n\n確認してください：\n' + students.warnings.concat(teachers.warnings).join('\n');
  }
  Logger.log(msg);
  try { SpreadsheetApp.getUi().alert(msg); } catch (e) { /* エディタから実行したときはログだけ */ }
}

/**
 * フォームの回答を {time, answers: {見出し: 回答}} の配列にする（古い順）。
 * グリッドの質問は、回答の配列に加えて行の見出しも answers['<見出し>#rows'] に入れる
 * （フォームの行を手で直していても、見出しの時刻で読めるようにするため）。
 */
function readResponses_(formId) {
  var form = FormApp.openById(formId);
  var rows = {};
  form.getItems(FormApp.ItemType.CHECKBOX_GRID).forEach(function (it) {
    rows[it.getTitle()] = it.asCheckboxGridItem().getRows();
  });
  return form.getResponses().map(function (r) {
    var answers = {};
    r.getItemResponses().forEach(function (ir) {
      var title = ir.getItem().getTitle();
      answers[title] = ir.getResponse();
      if (rows[title]) answers[title + '#rows'] = rows[title];
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

function komaLabels_(cfg) {
  cfg = cfg || CONFIG;
  return cfg.komas.map(function (k) { return k.no + '限 ' + k.start + '〜' + k.end; });
}

function lessonChoices_(cfg) {
  cfg = cfg || CONFIG;
  var out = [NONE];
  FORMS.forEach(function (f) {
    for (var n = 1; n <= cfg.maxTimesPerWeek; n++) out.push(f + ' 週' + n + '回');
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
  var k = cfg.komas[0];
  return toMin_(k.end) - toMin_(k.start);
}

/** 空き時間の枠の開始（分）。最初のコマの開始から最後のコマの終了まで、slotMinutes 刻み。 */
function cellStarts_(cfg) {
  cfg = cfg || CONFIG;
  var first = Math.min.apply(null, cfg.komas.map(function (k) { return toMin_(k.start); }));
  var last = Math.max.apply(null, cfg.komas.map(function (k) { return toMin_(k.end); }));
  var out = [];
  for (var t = first; t < last; t += cfg.slotMinutes) out.push(t);
  return out;
}

/** フォームの空き時間の行の見出し（例：16:00〜16:30）。 */
function cellLabels_(cfg) {
  cfg = cfg || CONFIG;
  return cellStarts_(cfg).map(function (t) { return toHhmm_(t) + '〜' + toHhmm_(t + cfg.slotMinutes); });
}

/** 空き時間シートの列（例：月16:00）。 */
function slotLabels_(cfg) {
  var out = [];
  cfg.days.forEach(function (d) { cellStarts_(cfg).forEach(function (t) { out.push(d + toHhmm_(t)); }); });
  return out;
}

/** 氏名の空白（全角も）を除いて、同じ人の回答をまとめるためのキーにする。 */
function nameKey_(name) {
  return String(name || '').replace(/[\s　]+/g, '');
}

/** 同じ氏名の回答は最後のものだけ残す（最初に回答した順に並べる）。 */
function latestByName_(responses) {
  var order = [];
  var latest = {};
  responses.slice().sort(function (a, b) { return a.time - b.time; }).forEach(function (r) {
    var key = nameKey_(r.answers[Q.name]);
    if (!key) return;
    if (!(key in latest)) order.push(key);
    latest[key] = r;
  });
  return order.map(function (k) { return latest[k]; });
}

/**
 * チェックボックスのグリッド（行=時間の枠, 列=曜日）の回答を「月16:00」の集合にする。
 * rows（フォームの行の見出し）があれば見出しの最初の時刻で、無ければ行の順番で枠を決める。
 */
function availSet_(grid, cfg, rows) {
  var starts = cellStarts_(cfg);
  var set = {};
  (grid || []).forEach(function (cols, i) {
    var t = rows && rows[i] != null ? toMin_(rows[i]) : starts[i];
    if (t == null || !cols) return;
    (Array.isArray(cols) ? cols : [cols]).forEach(function (d) { if (d) set[d + toHhmm_(t)] = true; });
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
  return [['コマ', '開始', '終了']].concat(cfg.komas.map(function (k) { return [k.no, k.start, k.end]; }));
}

/**
 * 生徒用フォームの回答から「生徒_受講希望」「生徒_空き時間」の表を作る。
 * previous には前回まとめた「生徒_受講希望」を渡す（同じ氏名には同じ生徒IDを使い、希望講師・固定の列を引き継ぐ）。
 */
function buildStudentSheets(responses, cfg, previous) {
  var prev = previousIds_(previous, '生徒ID');
  var slots = slotLabels_(cfg);
  var requests = [['生徒ID', '氏名', '学年', '科目', '形式', '週の回数', '希望講師（任意）', '固定（任意）', '要望']];
  var avail = [['生徒ID', '氏名'].concat(slots)];
  var warnings = [];
  latestByName_(responses).forEach(function (r) {
    var a = r.answers;
    var key = nameKey_(a[Q.name]);
    var name = String(a[Q.name]).trim();
    var id = idFor_(prev, 'S', key);
    var lessons = a[Q.lessons] || [];
    var count = 0;
    cfg.subjects.forEach(function (subj, i) {
      var m = String(lessons[i] || '').match(/^(集団|個別) 週(\d+)回$/);
      if (!m) return;
      var keep = prev.extra[key + '\t' + subj] || {};
      requests.push([id, name, a[Q.grade] || '', subj, m[1], m[2],
        keep['希望講師（任意）'] || '', keep['固定（任意）'] || '', count === 0 ? (a[Q.note] || '') : '']);
      count++;
    });
    var set = availSet_(a[Q.studentAvail], cfg, a[Q.studentAvail + '#rows']);
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
  var teachers = [['講師ID', '氏名'].concat(cfg.subjects, ['集団可', '個別可', '週の上限コマ'])];
  var avail = [['講師ID', '氏名'].concat(slots)];
  var warnings = [];
  latestByName_(responses).forEach(function (r) {
    var a = r.answers;
    var name = String(a[Q.name]).trim();
    var id = idFor_(prev, 'T', nameKey_(a[Q.name]));
    var subjects = [].concat(a[Q.teacherSubjects] || []);
    var forms = [].concat(a[Q.teacherForms] || []);
    var max = String(a[Q.teacherMax] || '').trim();
    teachers.push([id, name]
      .concat(cfg.subjects.map(function (s) { return subjects.indexOf(s) >= 0 ? '○' : ''; }))
      .concat([forms.indexOf('集団') >= 0 ? '○' : '', forms.indexOf('個別') >= 0 ? '○' : '', max]));
    var set = availSet_(a[Q.teacherAvail], cfg, a[Q.teacherAvail + '#rows']);
    avail.push([id, name].concat(slots.map(function (s) { return set[s] ? '○' : ''; })));
    if (!Object.keys(set).length) warnings.push('講師 ' + name + '：出勤できる時間が選ばれていません。');
  });
  return { teachers: teachers, avail: avail, warnings: warnings };
}

// テスト用（Apps Script では module が無いので何もしない）
if (typeof module !== 'undefined') {
  module.exports = {
    CONFIG: CONFIG, Q: Q, komaSheet: komaSheet, lessonChoices_: lessonChoices_, komaLabels_: komaLabels_,
    cellLabels_: cellLabels_,
    buildStudentSheets: buildStudentSheets, buildTeacherSheets: buildTeacherSheets,
  };
}
