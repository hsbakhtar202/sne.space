<?php
/**
 * Template Name: Locations template
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
	<?php cryout_before_content_hook(); ?>
	<div class="page type-page status-publish hentry">
		<div id="loading" style="text-align:center;"><img src="https://<?php echo $subd; ?>.space/wp-content/themes/<?php echo $stem; ?>-child-theme/loading.gif"><br>Loading...</div>
		<div style="overflow:auto;-webkit-overflow-scrolling:touch">
		<iframe id="themeframe" width=100% scrolling="no" src="https://<?php echo $subd; ?>.space/astrocats/astrocats/<?php echo $modu; ?>/output/html/<?php echo $stem; ?>-locations.html" style="display:block;border:none;width=100%;" onload="autoResize();"></iframe>
		</div>
	</div>
	<?php cryout_after_content_hook(); ?>
	</div><!-- #content -->
</section><!-- #container -->

<?php get_footer(); ?>
