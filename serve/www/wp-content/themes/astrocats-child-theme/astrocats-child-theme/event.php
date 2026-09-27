<?php
/**
 * Template Name: Event template
 *
 * A custom page template without sidebar.
 *
 * The "Template Name:" bit above allows this to be selectable
 * from a dropdown menu on the edit page screen.
 *
 * @package Cryout Creations
 * @subpackage parabola
 * @since parabola 0.5
 */

$tt = explode("\n", file_get_contents(__DIR__ . '/tt.dat'));
$stem = trim($tt[0]);
$modu = trim($tt[1]);
$subd = trim($tt[4]);

global $wp_query;
get_header();
?>

<section id="container" class="one-column">
	<div id="content" role="main">
<?php
	cryout_before_content_hook();
?>
	<div class="page type-page status-publish hentry">
<?php
	$rootpath = '/root/';
	$htmlpath = 'astrocats/astrocats/' . $modu . '/output/html/';
	function loadEventFrame($name, $entered_name = false) {
		global $rootpath, $htmlpath, $stem, $subd;
		if (file_exists($rootpath.$htmlpath.$name.'.html') ||
			file_exists($rootpath.$htmlpath.$name.'.html.gz')) { ?>
			<div id="loading"><img src="https://<?php echo $subd; ?>.space/wp-content/themes/astrocats-child-theme/loading.gif"><br>Loading...</div>
			<div style="overflow:auto;-webkit-overflow-scrolling:touch">
			<?php if ($entered_name) { ?>
			<div style="text-align:center; width:100%; color:orange"><strong>Warning:</strong> Exact event name "<?php echo rawurldecode($entered_name); ?>" not found, returning closest match.</div>
			<?php } ?>
			<iframe onload="autoResize();" width=100% id="themeframe" scrolling="no" src="https://<?php echo $subd; ?>.space/<?php echo $htmlpath.$name; ?>.html" style="display:block;border:none;width=100%;"></iframe>
			<script>iFrameResize({log:true, heightCalculationMethod:'max'})</script>
			</div>
<?php 		return true;
		}
		return false;
	}
	$oname = $wp_query->query_vars['eventname'];
	$eventname = rawurldecode($oname);
	$eventname = str_replace('.html', '', $eventname);
	$count = 1;
	if (is_numeric(substr($eventname, 0, 3)) && strlen($eventname) <= 4) {
		$eventname = 'SN'.$eventname;
	}
	if (is_numeric(substr($eventname, 0, 4)) && !is_numeric(substr($eventname, 4))) {
		$eventname = 'SN'.$eventname;
	}
	if (substr($eventname, 0, 2) == 'sn') {
		$eventname = str_replace('sn', 'SN', $eventname, $count);
	}
	if (substr($eventname, 0, 3) == 'SN ') {
		$eventname = str_replace('SN ', 'SN', $eventname, $count);
	}
	if (substr($eventname, 0, 2) == 'SN' && is_numeric(substr($eventname, 2, 3))) {
		if (strlen($eventname) == 7) {
			$eventname = strtoupper($eventname);
		} else {
			$eventname = substr($eventname, 0, 6) . strtolower(substr($eventname, 6));
		}
	}
	$nstr = file_get_contents('/var/www/html/' . $stem . '/astrocats/astrocats/' . $modu . '/output/names.min.json');
	$nbystr = file_get_contents('/var/www/html/' . $stem . '/astrocats/astrocats/' . $modu . '/output/names-by.min.json');
	$jsons = [json_decode($nstr, true), json_decode($nbystr, true)];
	$levs = [];
	// Temporary, remove later
	//if (loadEventFrame($eventname)) {
	//	return;
	//}
	foreach ($jsons as $json) {
		foreach ($json as $name => $entry) {
			$min_lev = 100;
			foreach ($entry as $alias) {
				if($alias == $eventname || str_replace('SN', 'AT', $eventname) == $alias) {
					if (loadEventFrame($name)) {
						$found = true;
					} elseif (loadEventFrame(str_replace('SN', 'AT', $name))) {
						$found = true;
					} else {
						foreach ($entry as $alias2) {
							if (loadEventFrame($alias2) ||
								loadEventFrame(str_replace('SN', 'AT', $alias2))) $found = true;
						}	
					}
					break 2;
				} else {
					$lev = levenshtein($alias, $eventname, 3, 1, 3);
					if ($lev < $min_lev) {
						$min_lev = $lev;
					}
				}
				$levs[$name] = $min_lev;
			}
		}
	}
	if (!$found) {
		// Getting really desperate here!
		if (min($levs) < 4) {
			$lev_name = array_search(min($levs), $levs);
			if (loadEventFrame($lev_name, $oname)) {
				$found = true;
			}
		}
	}
	if (!$found) {
?>
			<div style="text-align:center;">Error: Invalid event name "<?php echo $eventname; ?>"! [<?php echo $eventname; ?>]</div>
<?php
	}
?>
	</div>

	<?php cryout_after_content_hook(); ?>

	</div><!-- #content -->
		
</section><!-- #container -->

<?php get_footer(); ?>
