<?php
/**
 * PHP built-in server router for sne.space local Step 1.
 * Usage: php -S 127.0.0.1:8080 -t serve/www serve/router.php
 */
declare(strict_types=1);

$uri = urldecode(parse_url($_SERVER['REQUEST_URI'], PHP_URL_PATH) ?? '/');
$docroot = realpath(__DIR__ . '/www');
putenv('OSC_DOCROOT=' . $docroot);
$_SERVER['DOCUMENT_ROOT'] = $docroot;

// Gzip HTML: serve .html.gz when client asks and .html is empty/missing
if (preg_match('#^/astrocats/astrocats/supernovae/output/html/(.+)\.html$#', $uri, $m)) {
    $html = $docroot . $uri;
    $gz = $html . '.gz';
    if ((!is_file($html) || filesize($html) === 0) && is_file($gz)) {
        header('Content-Type: text/html; charset=utf-8');
        header('Content-Encoding: gzip');
        readfile($gz);
        return true;
    }
}

// /sne/{name}.json → event JSON
if (preg_match('#^/sne/(.+)\.json$#', $uri, $m)) {
    $name = str_replace('/', '_', rawurldecode($m[1]));
    $paths = [
        $docroot . '/astrocats/astrocats/supernovae/output/json/' . $name . '.json',
    ];
    // Also search year folders
    foreach (glob($docroot . '/astrocats/astrocats/supernovae/output/sne-*/' . $name . '.json') ?: [] as $p) {
        $paths[] = $p;
    }
    foreach ($paths as $p) {
        if (is_file($p)) {
            header('Content-Type: application/json; charset=utf-8');
            header('Content-Disposition: attachment; filename="' . $name . '.json"');
            readfile($p);
            return true;
        }
    }
    http_response_code(404);
    echo json_encode(['error' => 'not found', 'name' => $name]);
    return true;
}

// /sne/{name}/ or /event/{name}/ → resolver
if (preg_match('#^/(sne|event)/(.+?)/?$#', $uri, $m)) {
    $_GET['eventname'] = $m[2];
    require $docroot . '/event.php';
    return true;
}

// Homepage
if ($uri === '/' || $uri === '/index.php' || $uri === '/index.html') {
    require $docroot . '/index.php';
    return true;
}

// Static files under www
$file = $docroot . $uri;
if (is_file($file)) {
    return false; // let built-in server handle
}

// Directory index
if (is_dir($file) && is_file(rtrim($file, '/') . '/index.php')) {
    require rtrim($file, '/') . '/index.php';
    return true;
}

http_response_code(404);
header('Content-Type: text/plain');
echo "404 Not Found: $uri\n";
return true;
