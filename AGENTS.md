# Optional bookshelf

`templates/bookshelf.html` is an optional, single-file bookshelf. When asked for
a shelf, copy it to the desired location (for example `books/index.html`) and
populate the commented book links with single-file book HTML paths (`<slug>.html`)
and inlined `data:image/webp;base64,...` cover image URIs (returned as
`cover_data_uri` by `publish_book`) so the shelf and each book are self-contained
single HTML files with no external asset directories required. Give each cover
meaningful alt text for accessibility.

The default is a black, scrollable, responsive cover grid. Books open in an
iframe with a Back to shelf button. The unconfigured template is simply black.
Use the file's marked customization points for a title, kid's name, theme colors,
or other decoration only when the user asks in a follow-up prompt. No automatic
setup, book discovery, or publishing integration is required. Serve the shelf and
books together with the existing local/static hosting when reading on mobile.
