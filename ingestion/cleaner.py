from datetime import datetime, timezone
from bs4 import BeautifulSoup, Tag


class Cleaner:
    def clean(self, html: str, source_url: str, entity_type: str) -> tuple[str, dict]:
        """
        Convert a raw HTML page into clean prose text and a metadata dict.

        Returns a tuple of (clean_text, metadata) where:
          - clean_text is the extracted prose with embedded ### Section ### markers
          - metadata is the dict that becomes base_metadata for every Chunk
            produced from this page by the Chunker
        """
        # "html.parser" is Python's built-in HTML parser — no extra install needed.
        # "lxml" is faster but requires a C dependency. For our scraping volume
        # "html.parser" is fast enough and keeps the dependency list simpler.
        soup = BeautifulSoup(html, "html.parser")

        # These selectors match elements that contain navigation, ads, edit links,
        # category lists, and other wiki chrome — none of which is useful knowledge
        # for the RAG system. We remove them before extracting text so they don't
        # pollute chunks with irrelevant content.
        garbage_selectors = [
            "nav", "footer", "aside", "script", "style",
            ".infobox", ".toc", ".mw-jump-link", "#catlinks",
            ".printfooter", ".global-navigation", ".footer-main",
        ]

        # decompose() removes the element from the DOM tree entirely and frees
        # its memory. This is different from extract(), which removes it but
        # keeps it in memory in case you need it later. We don't, so decompose
        # is the right choice.
        for selector in garbage_selectors:
            for element in soup.select(selector):
                element.decompose()

        # The <h1> is the most reliable source of the page title on wiki pages.
        # We fall back to <title> (the browser tab title) which often includes
        # site name suffixes like "Malenia — Elden Ring Wiki", but it's better
        # than returning "Unknown Page".
        title_element = soup.find("h1") or soup.find("title")
        page_title = title_element.get_text(strip=True) if title_element else "Unknown Page"

        # Different wiki platforms use different CSS classes for the main content area.
        # .mw-parser-output is the standard MediaWiki class (used by wiki.gg).
        # #main-content is Fextralife's wrapper. We try both and fall back to
        # <body> (or the whole document) if neither exists, so we always get something.
        content_div = soup.select_one(".mw-parser-output") or soup.select_one("#main-content")
        if not content_div:
            content_div = soup.body if soup.body else soup

        structured_lines = []
        # current_section tracks which heading we're currently under as we walk
        # the DOM. It's used to label section transitions in the text.
        # Known limitation: at the end of the loop, current_section holds the
        # LAST heading on the page, so metadata["section"] reflects that rather
        # than each chunk's actual section. The ### markers embedded in the text
        # are what carry per-section information into chunks after splitting.
        current_section = "Introduction"

        # descendants yields every node in the subtree recursively — Tags, NavigableStrings,
        # Comments etc. We filter with isinstance(element, Tag) to skip raw text nodes
        # and only act on HTML elements we care about.
        for element in content_div.descendants:
            if isinstance(element, Tag):
                if element.name in ["h2", "h3", "h4"]:
                    # Update the active section and embed a visible marker into
                    # the text. The chunker will naturally split around these
                    # double-newline boundaries, so most chunks will start or
                    # end near a section boundary.
                    current_section = element.get_text(strip=True)
                    structured_lines.append(f"\n\n### {current_section} ###\n")

                elif element.name == "p":
                    # get_text(strip=True) returns all text content within the
                    # tag, including text inside nested elements like <strong>
                    # or <a>, with leading/trailing whitespace removed.
                    text = element.get_text(strip=True)
                    if text:
                        structured_lines.append(text)

                elif element.name == "table":
                    # Wiki pages use tables heavily for stat blocks, drop tables,
                    # and weapon data. get_text(" | ", strip=True) flattens the
                    # table into a single line with cells separated by " | ".
                    # This loses the grid structure but keeps the data readable
                    # as plain text for embedding purposes.
                    text = element.get_text(" | ", strip=True)
                    if text:
                        structured_lines.append(f"\n[Table Data: {text}]\n")

        clean_text = "\n".join(structured_lines)

        # This dict becomes base_metadata in the Chunker — every Chunk produced
        # from this page inherits these fields, plus chunk_index added by the Chunker.
        #
        # datetime.now(timezone.utc) is preferred over datetime.utcnow() because
        # utcnow() returns a naive datetime (no timezone info attached), which is
        # ambiguous. timezone.utc produces a timezone-aware datetime that Postgres
        # will store correctly as a TIMESTAMPTZ.
        metadata = {
            "source_url": source_url,
            "page_title": page_title,
            "section": current_section,   # last section on the page — see note above
            "entity_type": entity_type,
            "last_scraped_at": datetime.now(timezone.utc).isoformat(),
        }

        return clean_text, metadata

        

        
