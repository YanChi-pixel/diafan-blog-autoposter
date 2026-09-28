<?php
/**
 * Шаблонный тег: выводит анонс страницы сайта.
 *
 * Правка под конкретный сайт.
 *
 * Было:
 *     echo DB::query_result("SELECT [anons] FROM {site} WHERE id = ".$this->diafan->_site->id."");
 *
 * Проблема: анонс хранится у страницы-оболочки «Блог» (diafan_site), и она
 * же служит оболочкой для статей — поэтому вступление блога выводилось
 * в начале КАЖДОЙ статьи.
 *
 * Различить список и статью по $this->diafan->_site->module нельзя: на обоих
 * там 'news'. Зато таблица ЧПУ различает их точно — проверено запросом:
 *
 *     rewrite='news'          module_name='site'  (список блога)
 *     rewrite='news/<slug>'   module_name='news'  (статья)
 *
 * Поэтому модуль текущего адреса берём из diafan_rewrite. Анонс выводим
 * везде, кроме адресов, которые принадлежат модулю новостей.
 *
 * @package    DIAFAN.CMS
 * @author     diafan.ru
 * @version    7.0
 * @license    http://www.diafan.ru/license.html
 * @copyright  Copyright (c) 2003-2021 OOO «Диафан» (http://www.diafan.ru/)
 */

if (! defined('DIAFAN'))
{
    $path = __FILE__;
    while(! file_exists($path.'/includes/404.php'))
    {
        $parent = dirname($path);
        if($parent == $path) exit;
        $path = $parent;
    }
    include $path.'/includes/404.php';
}

// адрес текущей страницы без ведущих и замыкающих слэшей и без query-строки
$anons_path = '';
if (! empty($_SERVER['REQUEST_URI']))
{
    $anons_path = (string) parse_url($_SERVER['REQUEST_URI'], PHP_URL_PATH);
    $anons_path = trim($anons_path, '/');
}

// какому модулю принадлежит этот адрес по данным самой CMS
$anons_module = '';
if ($anons_path !== '')
{
    $anons_module = (string) DB::query_result(
        "SELECT module_name FROM {rewrite} WHERE rewrite='%s' AND trash='0' LIMIT 1",
        $anons_path
    );
}

// на страницах статей блога анонс страницы «Блог» не показываем
if ($anons_module !== 'news')
{
    echo DB::query_result("SELECT [anons] FROM {site} WHERE id = ".$this->diafan->_site->id."");
}
