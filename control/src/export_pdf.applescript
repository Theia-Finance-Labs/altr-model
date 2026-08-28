on run
	-- Staged inside PowerPoint's sandbox container, addressed via its redirected ~/Documents view.
	set pptxPath to "/Users/jakub/Documents/altr_deck.pptx"
	set pdfPath to "/Users/jakub/Documents/altr_deck_preview.pdf"
	tell application "Microsoft PowerPoint"
		activate
		delay 3
		open pptxPath
		delay 3
		save active presentation in pdfPath as save as PDF
		delay 2
		close active presentation saving no
	end tell
	return "ok"
end run
