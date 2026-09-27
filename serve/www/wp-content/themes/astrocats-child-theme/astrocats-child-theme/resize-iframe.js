function resizeWindowToContents() {
	console.log('resized window');
	jQuery('#themeframe').height(jQuery('#themeframe').contents().height());
}

function autoResize(){
	// setTimeout( resizeWindowToContents(), 400);
	document.getElementById('loading').style.display = 'none';
}

// window.onfocus = function() { autoResize(); };
