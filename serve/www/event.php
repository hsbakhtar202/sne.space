<?php
/**
 * Native event.php resolver (S1.3) — no WordPress.
 * Serves event HTML iframe shell for /sne/{name} and /event/{name}.
 */
declare(strict_types=1);

$modu = 'supernovae';
$stem = 'sne';
$htmlpath = 'astrocats/astrocats/' . $modu . '/output/html/';
$namesPath = __DIR__ . '/astrocats/astrocats/' . $modu . '/output/names.min.json';
$namesByPath = __DIR__ . '/astrocats/astrocats/' . $modu . '/output/names-by.min.json';

function html_exists(string $docroot, string $htmlpath, string $name): bool {
    $base = rtrim($docroot, '/') . '/' . $htmlpath . $name;
    return is_file($base . '.html') || is_file($base . '.html.gz');
}

function normalize_event_name(string $eventname): string {
    $eventname = str_replace('.html', '', $eventname);
    $count = 1;
    if (is_numeric(substr($eventname, 0, 3)) && strlen($eventname) <= 4) {
        $eventname = 'SN' . $eventname;
    }
    if (is_numeric(substr($eventname, 0, 4)) && !is_numeric(substr($eventname, 4))) {
        $eventname = 'SN' . $eventname;
    }
    if (substr($eventname, 0, 2) === 'sn') {
        $eventname = str_replace('sn', 'SN', $eventname, $count);
    }
    if (substr($eventname, 0, 3) === 'SN ') {
        $eventname = str_replace('SN ', 'SN', $eventname, $count);
    }
    if (substr($eventname, 0, 2) === 'SN' && is_numeric(substr($eventname, 2, 3))) {
        if (strlen($eventname) === 7) {
            $eventname = strtoupper($eventname);
        } else {
            $eventname = substr($eventname, 0, 6) . strtolower(substr($eventname, 6));
        }
    }
    return $eventname;
}

function name_to_filename(string $name): string {
    return str_replace('/', '_', $name);
}

function render_event_frame(string $name, ?string $entered = null): void {
    global $htmlpath;
    $src = '/' . $htmlpath . name_to_filename($name) . '.html';
    header('Content-Type: text/html; charset=utf-8');
    echo '<!DOCTYPE html><html><head>'
        . '<!-- Google tag (gtag.js) -->'
        . '<script async src="https://www.googletagmanager.com/gtag/js?id=G-P1SCVZ0V7T"></script>'
        . '<script>'
        . 'window.dataLayer = window.dataLayer || [];'
        . 'function gtag(){dataLayer.push(arguments);}'
        . 'gtag(\'js\', new Date());'
        . 'gtag(\'config\', \'G-P1SCVZ0V7T\');'
        . '</script>'
        . '<meta charset="utf-8"><title>'
        . htmlspecialchars($name) . ' — Open Supernova Catalog</title>'
        . '<style>body{margin:0;background:#111}#warn{text-align:center;color:orange;padding:.5rem;background:#222}'
        . 'iframe{border:0;width:100%;min-height:100vh;display:block;background:#fff}</style></head><body>';
    if ($entered !== null) {
        echo '<div id="warn"><strong>Warning:</strong> Exact event name "'
            . htmlspecialchars(rawurldecode($entered))
            . '" not found, returning closest match.</div>';
    }
    echo '<iframe id="themeframe" src="' . htmlspecialchars($src) . '"></iframe></body></html>';
}

$docroot = __DIR__;
$oname = $_GET['eventname'] ?? '';
$oname = rawurldecode($oname);
$eventname = normalize_event_name($oname);

$names = [];
if (is_file($namesPath)) {
    $names[] = json_decode(file_get_contents($namesPath), true) ?: [];
}
if (is_file($namesByPath)) {
    $names[] = json_decode(file_get_contents($namesByPath), true) ?: [];
}

$found = false;
$levs = [];

foreach ($names as $json) {
    foreach ($json as $name => $entry) {
        if (!is_array($entry)) {
            continue;
        }
        $min_lev = 100;
        foreach ($entry as $alias) {
            if (!is_string($alias)) {
                continue;
            }
            if ($alias === $eventname || str_replace('SN', 'AT', $eventname) === $alias) {
                $candidates = [$name, str_replace('SN', 'AT', $name)];
                foreach ($entry as $alias2) {
                    if (is_string($alias2)) {
                        $candidates[] = $alias2;
                        $candidates[] = str_replace('SN', 'AT', $alias2);
                    }
                }
                foreach ($candidates as $cand) {
                    if (html_exists($docroot, $htmlpath, name_to_filename($cand))) {
                        render_event_frame($cand);
                        exit;
                    }
                }
                // No HTML yet — still accept canonical name and serve JSON shell or placeholder
                render_event_frame($name);
                exit;
            }
            $lev = levenshtein($alias, $eventname, 3, 1, 3);
            if ($lev < $min_lev) {
                $min_lev = $lev;
            }
        }
        $levs[$name] = $min_lev;
    }
}

if (!$found && $levs && min($levs) < 4) {
    $lev_name = array_search(min($levs), $levs, true);
    if (is_string($lev_name)) {
        render_event_frame($lev_name, $oname);
        exit;
    }
}

http_response_code(404);
header('Content-Type: text/html; charset=utf-8');
echo '<!DOCTYPE html><html><body style="text-align:center;font-family:sans-serif;padding:2rem">'
    . 'Error: Invalid event name "' . htmlspecialchars($eventname) . '"!'
    . '</body></html>';
