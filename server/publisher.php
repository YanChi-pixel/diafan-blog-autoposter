<?php
/**
 * publisher.php — единственная точка записи статей в блог на Diafan.CMS.
 *
 * Деплоится по FTP в корень сайта под случайным именем.
 * Работает «изнутри» Diafan.CMS: бутстрап ядра + DB::query + штатная
 * загрузка изображений, поэтому кэш, индексы и нарезка картинок
 * отрабатывают так же, как при сохранении через админку.
 *
 * Вызов:
 *   GET  ?action=inspect   — диагностика: схема таблиц, вариации картинок,
 *                            образцы существующих статей и ЧПУ
 *   POST ?action=publish   — публикация статьи (JSON в теле)
 *
 * Авторизация: заголовок X-Publisher-Token (или ?token=).
 * Публикация идемпотентна по полю external_id.
 */

define('DIAFAN', 1);
define('ABSOLUTE_PATH', dirname(__FILE__) . '/');

include_once(ABSOLUTE_PATH . "config.php");

define('IS_ADMIN', 1);

include_once ABSOLUTE_PATH . 'includes/custom.php';
include_once ABSOLUTE_PATH . 'includes/developer.php';
include_once ABSOLUTE_PATH . 'includes/diafan.php';
include_once ABSOLUTE_PATH . 'includes/file.php';

header('Content-Type: application/json; charset=utf-8');
header('X-Robots-Tag: noindex, nofollow');

// ===========================================================================
// СЕКРЕТ — подставляется при деплое
// ===========================================================================
$PUBLISHER_TOKEN = '__PUBLISHER_TOKEN__';

// ===========================================================================
// Утилиты
// ===========================================================================

function pub_out($data, $code = 200)
{
    http_response_code($code);
    echo json_encode($data, JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT);
    exit;
}

function pub_fail($message, $code = 400)
{
    pub_out(array('ok' => false, 'error' => $message), $code);
}

function pub_token()
{
    if (! empty($_SERVER['HTTP_X_PUBLISHER_TOKEN'])) {
        return $_SERVER['HTTP_X_PUBLISHER_TOKEN'];
    }
    if (! empty($_POST['token'])) {
        return $_POST['token'];
    }
    if (! empty($_GET['token'])) {
        return $_GET['token'];
    }
    return '';
}

function pub_body()
{
    $raw = file_get_contents('php://input');
    if ($raw === false || $raw === '') {
        return array();
    }
    $data = json_decode($raw, true);
    if (! is_array($data)) {
        pub_fail('тело запроса не является корректным JSON');
    }
    return $data;
}

/** Колонки таблицы (кэшируется в рамках запроса). */
function pub_columns($table)
{
    static $cache = array();
    if (isset($cache[$table])) {
        return $cache[$table];
    }
    $cols = array();
    $rows = DB::query_fetch_all("SHOW COLUMNS FROM {" . $table . "}");
    foreach ($rows as $row) {
        $cols[] = $row['Field'];
    }
    $cache[$table] = $cols;
    return $cols;
}

/** Типы колонок: имя => 'enum(...)' / 'int unsigned' и т.п. */
function pub_column_types($table)
{
    static $cache = array();
    if (isset($cache[$table])) {
        return $cache[$table];
    }
    $types = array();
    $rows = DB::query_fetch_all("SHOW COLUMNS FROM {" . $table . "}");
    foreach ($rows as $row) {
        $types[$row['Field']] = strtolower($row['Type']);
    }
    $cache[$table] = $types;
    return $types;
}

/**
 * Имя колонки с учётом мультиязычного суффикса «1».
 * Diafan хранит переводимые поля как name1, text1 и т.п.
 */
function pub_col($table, $base)
{
    $cols = pub_columns($table);
    if (in_array($base . '1', $cols, true)) {
        return $base . '1';
    }
    if (in_array($base, $cols, true)) {
        return $base;
    }
    return null;
}

/** Удаляет привязанные к новости изображения: строки в корзину, файлы с диска.
 *
 *  Удаляются ТОЛЬКО файлы этой новости — по точным именам из таблицы images.
 */
function pub_remove_images($id, &$removed = array())
{
    $rows = DB::query_fetch_all(
        "SELECT name FROM {images} WHERE module_name='news' AND element_id=%d", $id
    );
    $names = array();
    foreach ($rows as $r) {
        if (! empty($r['name'])) {
            $names[] = $r['name'];
        }
    }
    DB::query("UPDATE {images} SET trash='1' WHERE module_name='news' AND element_id=%d", $id);

    if ($names) {
        foreach (glob(ABSOLUTE_PATH . 'userfls/news/*') as $dir) {
            if (! is_dir($dir)) {
                continue;
            }
            foreach ($names as $file_name) {
                $path = $dir . '/' . $file_name;
                if (is_file($path)) {
                    $removed[] = str_replace(ABSOLUTE_PATH, '', $path);
                    @unlink($path);
                }
            }
        }
    }
    return $names;
}

/** Загружает обложку новости из base64 и проставляет alt/title. */
function pub_upload_image($diafan, $news_id, $site_id, $name, $binary, $alt)
{
    $tmp = ABSOLUTE_PATH . 'tmp/pub_' . $news_id . '_' . uniqid() . '.jpg';
    file_put_contents($tmp, $binary);
    $img_name = preg_replace(
        '/[^a-z0-9]+/', '',
        strtolower(substr($diafan->translit($name), 0, 30))
    );
    try {
        Custom::inc('includes/image.php');
        $diafan->_images->upload(
            $news_id, 'news', 'element', (int) $site_id, $tmp, $img_name, true, 0, ''
        );
        DB::query(
            "UPDATE {images} SET alt1='%s', title1='%s'
             WHERE module_name='news' AND element_id=%d AND trash='0'",
            $alt, $alt, $news_id
        );
        $files = array();
        foreach (array('smalla', 'large', 'medium', 'small') as $var) {
            $found = glob(ABSOLUTE_PATH . 'userfls/news/' . $var . '/*' . $img_name . '*');
            if ($found) {
                $files[$var] = array(basename($found[0]), filesize($found[0]));
            }
        }
        @unlink($tmp);
        return array('ok' => true, 'name' => $img_name,
                     'bytes' => strlen($binary), 'variations' => $files);
    } catch (Throwable $e) {
        @unlink($tmp);
        return array('ok' => false, 'error' => $e->getMessage());
    }
}

/** Имя файла-обложки ищется по последней картинке новости. */
function pub_cover_name($id)
{
    $row = DB::query_fetch_array(
        "SELECT name FROM {images} WHERE module_name='news' AND element_id=%d
         AND trash='0' ORDER BY sort DESC, id DESC LIMIT 1", $id
    );
    return $row ? $row['name'] : '';
}

/** Единое сопоставление полей статьи с колонками Diafan. */
function pub_build_values(array $body, $external_id, $slug = '')
{
    $created = ! empty($body['created']) ? (int) $body['created'] : time();
    $act = isset($body['act']) ? (int) $body['act'] : 1;

    return array(
        'name'        => $body['name'],
        'anons'       => isset($body['anons']) ? $body['anons'] : '',
        'text'        => $body['text'],
        'cat_id'      => isset($body['cat_id']) ? (int) $body['cat_id'] : 0,
        'site_id'     => isset($body['site_id']) ? (int) $body['site_id'] : 0,
        'created'     => $created,
        'act'         => $act,
        'prior'       => 0,
        'title_meta'  => isset($body['title_meta']) ? $body['title_meta'] : '',
        'keywords'    => isset($body['keywords']) ? $body['keywords'] : '',
        'descr'       => isset($body['descr']) ? $body['descr'] : '',
        'canonical'   => isset($body['canonical']) ? $body['canonical'] : '',
        'noindex'     => 0,
        'changefreq'  => isset($body['changefreq']) ? $body['changefreq'] : 'monthly',
        'priority'    => isset($body['priority']) ? (string) $body['priority'] : '0',
        'map_no_show' => 0,
        'access'      => 0,
        'trash'       => 0,
        'timeedit'    => time(),
        'admin_id'    => isset($body['admin_id']) ? (int) $body['admin_id'] : 0,
        'import_id'   => $external_id,
    );
}

/** UPDATE уже существующей новости теми же полями (для правок и обновлений). */
function pub_update($table, $id, array $values, $debug_sql = null)
{
    $cols = pub_columns($table);
    $types = pub_column_types($table);
    $sets = array();
    foreach ($values as $base => $value) {
        $col = in_array($base . '1', $cols, true) ? $base . '1'
             : (in_array($base, $cols, true) ? $base : null);
        if ($col === null || $col === 'import_id') {
            continue;
        }
        $is_enum = isset($types[$col]) && strpos($types[$col], 'enum(') === 0;
        if (! $is_enum && (is_int($value) || is_bool($value))) {
            $sets[] = '`' . $col . '`=' . (int) $value;
        } else {
            $sets[] = '`' . $col . "`='" . DB::escape_string((string) $value) . "'";
        }
    }
    if (! $sets) {
        throw new Exception('нечего обновлять');
    }
    $sql = 'UPDATE `' . DB_PREFIX . $table . '` SET ' . implode(', ', $sets)
         . ' WHERE id=' . (int) $id;
    try {
        DB::$backend->query($sql);
    } catch (DB_exception $e) {
        throw new Exception('ошибка SQL: ' . $e->getMessage());
    }
    return true;
}

/** Собирает INSERT только из тех колонок, которые реально есть в таблице.
 *
 *  Экранирование делаем сами и обращаемся к бэкенду напрямую: DB::query()
 *  при ошибке молча возвращает false, а нам нужен текст ошибки.
 */
function pub_insert($table, array $values, &$debug_sql = null)
{
    $cols = pub_columns($table);
    $use = array();
    foreach ($values as $base => $value) {
        $col = in_array($base . '1', $cols, true) ? $base . '1'
             : (in_array($base, $cols, true) ? $base : null);
        if ($col !== null) {
            $use[$col] = $value;
        }
    }
    if (! $use) {
        throw new Exception('нет колонок для вставки в ' . $table);
    }

    $names = array();
    $vals = array();
    $types = pub_column_types($table);
    foreach ($use as $col => $value) {
        $names[] = '`' . $col . '`';
        $is_enum = isset($types[$col]) && strpos($types[$col], 'enum(') === 0;
        // ВАЖНО: целое число в ENUM MySQL трактует как ИНДЕКС значения,
        // а не как само значение. Поэтому enum-поля всегда квотируем.
        if (! $is_enum && (is_int($value) || is_bool($value))) {
            $vals[] = (string) (int) $value;
        } else {
            $vals[] = "'" . DB::escape_string((string) $value) . "'";
        }
    }

    $sql = 'INSERT INTO `' . DB_PREFIX . $table . '` (' . implode(', ', $names) . ')'
         . ' VALUES (' . implode(', ', $vals) . ')';
    $debug_sql = substr($sql, 0, 400);

    try {
        DB::$backend->query($sql);
    } catch (DB_exception $e) {
        throw new Exception('ошибка SQL: ' . $e->getMessage());
    }
    return DB::insert_id();
}

function pub_dir_size($path)
{
    $total = 0;
    if (! is_dir($path)) {
        return 0;
    }
    foreach (new RecursiveIteratorIterator(
        new RecursiveDirectoryIterator($path, FilesystemIterator::SKIP_DOTS)
    ) as $file) {
        $total += $file->getSize();
    }
    return $total;
}

function pub_rimraf($path)
{
    if (! is_dir($path)) {
        return @unlink($path);
    }
    foreach (scandir($path) as $item) {
        if ($item === '.' || $item === '..') {
            continue;
        }
        pub_rimraf($path . '/' . $item);
    }
    return @rmdir($path);
}

// ===========================================================================
// Авторизация
// ===========================================================================

if (! hash_equals($PUBLISHER_TOKEN, (string) pub_token())) {
    pub_fail('forbidden', 403);
}

// ===========================================================================
// Бутстрап ядра
// ===========================================================================

try {
    include_once(ABSOLUTE_PATH . 'includes/core.php');
    include_once ABSOLUTE_PATH . 'includes/init.php';
    $diafan = new Init();
} catch (Throwable $e) {
    pub_fail('bootstrap failed: ' . $e->getMessage(), 500);
}

$action = isset($_GET['action']) ? $_GET['action'] : 'inspect';

// ===========================================================================
// INSPECT — диагностика окружения
// ===========================================================================

if ($action === 'inspect') {
    try {
        $out = array('ok' => true, 'cms_version' => defined('VERSION_CMS') ? VERSION_CMS : '?');

        // --- схема таблицы новостей ---
        $out['news_columns'] = pub_columns('news');
        $out['rewrite_columns'] = pub_columns('rewrite');
        $out['images_columns'] = pub_columns('images');

        // --- вариации изображений ---
        $out['images_variations'] = DB::query_fetch_all("SELECT * FROM {images_variations}");

        // --- образцы ЧПУ новостей: формат rewrite ---
        $out['rewrite_samples'] = DB::query_fetch_all(
            "SELECT id, rewrite, module_name, element_id, element_type FROM {rewrite}
             WHERE module_name='news' AND trash='0' ORDER BY id DESC LIMIT 10"
        );

        // --- сколько всего новостей и последняя ---
        $out['news_count'] = (int) DB::query_result("SELECT COUNT(*) FROM {news} WHERE trash='0'");
        $last = DB::query_fetch_array(
            "SELECT * FROM {news} WHERE trash='0' ORDER BY id DESC LIMIT 1"
        );
        if ($last) {
            // текст может быть большим — вернём фрагмент для разбора разметки
            foreach (array('text1', 'text') as $k) {
                if (isset($last[$k])) {
                    $last[$k . '_HEAD'] = mb_substr($last[$k], 0, 600, 'UTF-8');
                    $last[$k . '_TAIL'] = mb_substr($last[$k], -900, null, 'UTF-8');
                    $last[$k . '_LEN'] = mb_strlen($last[$k], 'UTF-8');
                    unset($last[$k]);
                }
            }
            foreach (array('anons1', 'anons') as $k) {
                if (isset($last[$k]) && is_string($last[$k])) {
                    $last[$k] = mb_substr($last[$k], 0, 300, 'UTF-8');
                }
            }
        }
        $out['last_news'] = $last;

        // --- категории новостей ---
        try {
            $out['news_categories'] = DB::query_fetch_all("SELECT * FROM {news_category}");
        } catch (Throwable $e) {
            $out['news_categories'] = 'нет таблицы: ' . $e->getMessage();
        }

        // --- страница сайта, к которой привязан модуль ---
        $out['news_site'] = DB::query_fetch_all(
            "SELECT id, name1, parent_id, act1 FROM {site} WHERE id IN
             (SELECT site_id FROM {rewrite} WHERE module_name='news' LIMIT 20)"
        );

        // --- админ-пользователи (для admin_id) ---
        $out['admins'] = DB::query_fetch_all(
            "SELECT id, name, mail, act FROM {users} WHERE role_id=1 OR id IN
             (SELECT user_id FROM {users_role} WHERE role_id=1) LIMIT 10"
        );

        // --- сигнатура $diafan->_images->upload() ---
        try {
            $ref = new ReflectionMethod(get_class($diafan->_images), 'upload');
            $params = array();
            foreach ($ref->getParameters() as $p) {
                $params[] = array(
                    'name'     => $p->getName(),
                    'optional' => $p->isOptional(),
                    'default'  => $p->isDefaultValueAvailable() ? var_export($p->getDefaultValue(), true) : null,
                );
            }
            $out['images_upload_signature'] = array(
                'class'  => get_class($diafan->_images),
                'method' => 'upload',
                'params' => $params,
                'file'   => $ref->getFileName(),
                'line'   => $ref->getStartLine(),
            );
        } catch (Throwable $e) {
            $out['images_upload_signature'] = 'error: ' . $e->getMessage();
        }

        // --- кэш ---
        try {
            $out['cache_class'] = get_class($diafan->_cache);
            $out['cache_methods'] = get_class_methods($diafan->_cache);
        } catch (Throwable $e) {
            $out['cache_class'] = 'error: ' . $e->getMessage();
        }

        // --- администраторы сайта ---
        try {
            $out['admin_users'] = DB::query_fetch_all(
                "SELECT id, name, mail, act FROM {admin} LIMIT 10"
            );
        } catch (Throwable $e) {
            $out['admin_users'] = 'error: ' . $e->getMessage();
        }

        // --- содержимое каталога cache ---
        $cache_dirs = array();
        foreach (array('cache', 'cache/css', 'cache/js') as $d) {
            $full = ABSOLUTE_PATH . $d;
            $cache_dirs[$d] = array(
                'exists' => is_dir($full),
                'size'   => pub_dir_size($full),
                'items'  => is_dir($full) ? count(scandir($full)) - 2 : 0,
            );
        }
        $out['cache_dirs'] = $cache_dirs;

        // --- права на запись ---
        $out['writable'] = array(
            'tmp'     => is_writable(ABSOLUTE_PATH . 'tmp'),
            'cache'   => is_writable(ABSOLUTE_PATH . 'cache'),
            'userfls' => is_writable(ABSOLUTE_PATH . 'userfls'),
        );

        // --- существующие каталоги картинок новостей ---
        $variations = array();
        foreach (glob(ABSOLUTE_PATH . 'userfls/news/*', GLOB_ONLYDIR) as $dir) {
            $variations[basename($dir)] = count(glob($dir . '/*'));
        }
        $out['news_image_dirs'] = $variations;

        pub_out($out);
    } catch (Throwable $e) {
        pub_fail('inspect failed: ' . $e->getMessage(), 500);
    }
}

// ===========================================================================
// RAW — исходный текст статьи как он лежит в БД (для разбора разметки)
// ===========================================================================

if ($action === 'raw') {
    try {
        $id = isset($_GET['id']) ? (int) $_GET['id'] : 0;
        $row = $id
            ? DB::query_fetch_array("SELECT * FROM {news} WHERE id=%d LIMIT 1", $id)
            : DB::query_fetch_array("SELECT * FROM {news} WHERE trash='0' ORDER BY id DESC LIMIT 1");
        if (! $row) {
            pub_fail('новость не найдена', 404);
        }
        // массив изображений, привязанных к новости
        $imgs = DB::query_fetch_all(
            "SELECT id, name, type, alt1, title1, sort, size FROM {images}
             WHERE module_name='news' AND element_id=%d AND trash='0' ORDER BY sort", $row['id']
        );
        pub_out(array('ok' => true, 'news' => $row, 'images' => $imgs));
    } catch (Throwable $e) {
        pub_fail('raw failed: ' . $e->getMessage(), 500);
    }
}

// ===========================================================================
// LINKS — карта внутренних ссылок: element_id <-> URL страниц сайта
// ===========================================================================

if ($action === 'links') {
    try {
        $rows = DB::query_fetch_all(
            "SELECT r.rewrite, r.element_id, r.element_type, r.module_name,
                    CASE WHEN r.module_name='site' THEN s.name1 ELSE n.name1 END AS name1,
                    n.created AS news_created
             FROM {rewrite} r
             LEFT JOIN {site} s ON (s.id = r.element_id AND r.module_name='site')
             LEFT JOIN {news} n ON (n.id = r.element_id AND r.module_name='news')
             WHERE r.module_name IN ('site','news') AND r.trash='0'
             ORDER BY r.module_name, r.element_id"
        );
        pub_out(array('ok' => true, 'count' => count($rows), 'links' => $rows));
    } catch (Throwable $e) {
        pub_fail('links failed: ' . $e->getMessage(), 500);
    }
}

// ===========================================================================
// DELETE — откат публикации (в корзину Diafan, с чисткой ЧПУ и картинок)
// ===========================================================================

if ($action === 'delete') {
    try {
        $id = isset($_GET['id']) ? (int) $_GET['id'] : 0;
        if (! $id) {
            pub_fail('не указан id');
        }
        $row = DB::query_fetch_array("SELECT id, name1 FROM {news} WHERE id=%d", $id);
        if (! $row) {
            pub_fail(sprintf('новость %d не найдена', $id), 404);
        }

        // какие файлы принадлежат именно этой новости
        $removed = array();
        pub_remove_images($id, $removed);

        DB::query("UPDATE {news} SET trash='1' WHERE id=%d", $id);
        DB::query("UPDATE {rewrite} SET trash='1' WHERE module_name='news' AND element_id=%d", $id);

        try {
            $diafan->_cache->flush();
        } catch (Throwable $e) {
            // не критично
        }
        pub_out(array('ok' => true, 'trashed_id' => $id, 'name' => $row['name1'],
                      'removed_files' => $removed));
    } catch (Throwable $e) {
        pub_fail('delete failed: ' . $e->getMessage(), 500);
    }
}

// ===========================================================================
// SET_IMAGE — замена обложки уже опубликованной статьи
// ===========================================================================

if ($action === 'set_image') {
    if (strtoupper($_SERVER['REQUEST_METHOD']) !== 'POST') {
        pub_fail('нужен POST');
    }
    try {
        $body = pub_body();
        $id = isset($body['id']) ? (int) $body['id'] : 0;
        if (! $id) {
            pub_fail('не указан id новости');
        }
        if (empty($body['image_base64'])) {
            pub_fail('не передано поле image_base64');
        }
        $row = DB::query_fetch_array(
            "SELECT id, name1, site_id FROM {news} WHERE id=%d", $id
        );
        if (! $row) {
            pub_fail(sprintf('новость %d не найдена', $id), 404);
        }
        $binary = base64_decode($body['image_base64'], true);
        if ($binary === false) {
            pub_fail('image_base64 не декодируется');
        }

        $removed = array();
        if (empty($body['keep_existing'])) {
            pub_remove_images($id, $removed);
        }

        $alt = isset($body['image_alt']) ? $body['image_alt'] : $row['name1'];
        $info = pub_upload_image($diafan, $id, $row['site_id'], $row['name1'],
                                 $binary, $alt);

        DB::query("UPDATE {news} SET timeedit=%d WHERE id=%d", time(), $id);
        try {
            $diafan->_cache->flush();
        } catch (Throwable $e) {
            // не критично
        }
        pub_out(array('ok' => $info['ok'], 'id' => $id, 'name' => $row['name1'],
                      'removed_files' => $removed, 'image' => $info));
    } catch (Throwable $e) {
        pub_fail('set_image failed: ' . $e->getMessage(), 500);
    }
}

// ===========================================================================
// SITEINFO — поля страницы сайта (для отладки шаблонов)
// ===========================================================================

if ($action === 'siteinfo') {
    try {
        $id = isset($_GET['id']) ? (int) $_GET['id'] : 0;
        if (! $id) {
            pub_fail('не указан id страницы сайта');
        }
        $row = DB::query_fetch_array("SELECT * FROM {site} WHERE id=%d", $id);
        if (! $row) {
            pub_fail(sprintf('страница %d не найдена', $id), 404);
        }
        // длинные поля отдаём фрагментом
        foreach ($row as $k => $v) {
            if (is_string($v) && mb_strlen($v, 'UTF-8') > 400) {
                $row[$k] = mb_substr($v, 0, 400, 'UTF-8') . '… [' .
                           mb_strlen($v, 'UTF-8') . ' символов]';
            }
        }
        pub_out(array('ok' => true, 'site' => $row));
    } catch (Throwable $e) {
        pub_fail('siteinfo failed: ' . $e->getMessage(), 500);
    }
}

// ===========================================================================
// CLEARCACHE — сброс файлового кэша CMS (нужен после правки шаблонов)
// ===========================================================================

if ($action === 'clearcache') {
    try {
        $result = array();
        try {
            $diafan->_cache->flush();
            $result['flush'] = 'ok';
        } catch (Throwable $e) {
            $result['flush'] = 'failed: ' . $e->getMessage();
        }

        // подчищаем скомпилированные шаблоны и css/js-сборки
        $cleared = array();
        foreach (array('cache', '.cache') as $d) {
            $full = ABSOLUTE_PATH . $d;
            if (! is_dir($full)) {
                continue;
            }
            $n = 0;
            foreach (scandir($full) as $item) {
                if ($item === '.' || $item === '..') {
                    continue;
                }
                pub_rimraf($full . '/' . $item);
                $n++;
            }
            $cleared[$d] = $n;
        }
        $result['cleared'] = $cleared;
        pub_out(array('ok' => true, 'cache' => $result));
    } catch (Throwable $e) {
        pub_fail('clearcache failed: ' . $e->getMessage(), 500);
    }
}

// ===========================================================================
// PUBLISH — публикация статьи
// ===========================================================================

if ($action === 'publish') {
    if (strtoupper($_SERVER['REQUEST_METHOD']) !== 'POST') {
        pub_fail('нужен POST');
    }

    try {
        $body = pub_body();
        $dry_run = ! empty($body['dry_run']);

        // ---------- валидация входа ----------
        foreach (array('name', 'text', 'slug') as $required) {
            if (empty($body[$required])) {
                pub_fail('не заполнено обязательное поле: ' . $required);
            }
        }
        $external_id = isset($body['external_id']) ? (string) $body['external_id'] : '';
        $slug = trim($body['slug'], "/ \t\n\r\0\x0B");

        if (! preg_match('~^[a-z0-9][a-z0-9\-]{1,60}$~', $slug)) {
            pub_fail('некорректный slug: ' . $slug);
        }

        // ---------- идемпотентность ----------
        if ($external_id !== '' && pub_col('news', 'import_id') !== null) {
            $col = pub_col('news', 'import_id');
            $exists = DB::query_result(
                "SELECT id FROM {news} WHERE `" . $col . "`='%s' LIMIT 1", $external_id
            );
            if ($exists) {
                pub_out(array(
                    'ok'      => true,
                    'skipped' => true,
                    'reason'  => 'уже опубликовано (external_id=' . $external_id . ')',
                    'id'      => (int) $exists,
                ));
            }
        }

        // ---------- занятость ЧПУ ----------
        $prefix = isset($body['rewrite_prefix']) ? trim($body['rewrite_prefix'], '/') : 'news';
        $full_rewrite = $prefix . '/' . $slug;
        $taken = DB::query_result(
            "SELECT id FROM {rewrite} WHERE rewrite='%s' AND trash='0' LIMIT 1", $full_rewrite
        );
        if ($taken) {
            pub_fail('ЧПУ уже занят: ' . $full_rewrite, 409);
        }

        // ---------- сборка значений ----------
        $values = pub_build_values($body, $external_id, $slug);

        if ($dry_run) {
            pub_out(array(
                'ok'            => true,
                'dry_run'       => true,
                'would_insert'  => $values,
                'would_rewrite' => $full_rewrite,
                'columns'       => pub_columns('news'),
            ));
        }

        // ---------- запись ----------
        $sql_debug = null;
        $news_id = pub_insert('news', $values, $sql_debug);
        if (! $news_id) {
            pub_fail('не удалось создать запись новости. SQL: ' . $sql_debug, 500);
        }

        DB::query(
            "INSERT INTO {rewrite} (rewrite, module_name, element_id, element_type, trash, import)
             VALUES ('%s', 'news', %d, 'element', '0', 1)",
            $full_rewrite, $news_id
        );

        // ---------- изображение ----------
        // Сигнатура Diafan: upload(element_id, module_name, element_type, site_id,
        //                        tmpfile, new_name, handle=false, param_id=0, tmpcode='')
        $image_info = null;
        if (! empty($body['image_base64'])) {
            $binary = base64_decode($body['image_base64'], true);
            if ($binary === false) {
                $image_info = array('ok' => false, 'error' => 'image_base64 не декодируется');
            } else {
                $alt = isset($body['image_alt']) ? $body['image_alt'] : $body['name'];
                $image_info = pub_upload_image(
                    $diafan, $news_id, $values['site_id'], $body['name'], $binary, $alt
                );
            }
        }

        // ---------- сброс кэша ----------
        $cache_info = 'not attempted';
        try {
            $diafan->_cache->flush();
            $cache_info = 'flush() ok';
        } catch (Throwable $e) {
            $cache_info = 'flush() failed: ' . $e->getMessage();
        }

        pub_out(array(
            'ok'       => true,
            'id'       => (int) $news_id,
            'url'      => 'https://' . $_SERVER['HTTP_HOST'] . '/' . $full_rewrite . '/',
            'rewrite'  => $full_rewrite,
            'act'      => (int) $values['act'],
            'image'    => $image_info,
            'cache'    => $cache_info,
        ));
    } catch (Throwable $e) {
        pub_fail('publish failed: ' . $e->getMessage(), 500);
    }
}

// ===========================================================================
// UPDATE — правка уже опубликованной статьи (обновление контента, dateModified)
// ===========================================================================

if ($action === 'update') {
    if (strtoupper($_SERVER['REQUEST_METHOD']) !== 'POST') {
        pub_fail('нужен POST');
    }
    try {
        $body = pub_body();
        $id = isset($body['id']) ? (int) $body['id'] : 0;
        if (! $id) {
            pub_fail('не указан id новости');
        }
        $row = DB::query_fetch_array("SELECT id FROM {news} WHERE id=%d", $id);
        if (! $row) {
            pub_fail(sprintf('новость %d не найдена', $id), 404);
        }
        $external_id = isset($body['external_id']) ? (string) $body['external_id'] : '';
        $values = pub_build_values($body, $external_id);
        $debug_sql = null;

        if (! empty($body['dry_run'])) {
            pub_out(array('ok' => true, 'dry_run' => true, 'would_update' => $values));
        }

        pub_update('news', $id, $values, $debug_sql);

        $rewrite = '';
        if (! empty($body['slug'])) {
            $prefix = isset($body['rewrite_prefix']) ? trim($body['rewrite_prefix'], '/') : 'news';
            $rewrite = $prefix . '/' . trim($body['slug'], '/');
            DB::query(
                "UPDATE {rewrite} SET rewrite='%s' WHERE module_name='news' AND element_id=%d",
                $rewrite, $id
            );
        }

        try {
            $diafan->_cache->flush();
        } catch (Throwable $e) {
            // не критично
        }

        pub_out(array(
            'ok'      => true,
            'id'      => $id,
            'rewrite' => $rewrite,
            'act'     => (int) $values['act'],
            'columns' => array_keys($values),
        ));
    } catch (Throwable $e) {
        pub_fail('update failed: ' . $e->getMessage(), 500);
    }
}

pub_fail('неизвестное действие: ' . $action, 404);
