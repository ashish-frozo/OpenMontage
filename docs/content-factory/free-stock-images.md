# Free stock-image sourcing

Two MCP operations provide a deliberate search → select → download flow:

| Operation | Inputs | Output |
|---|---|---|
| `stock_image_search` | Existing `project_id`, `query`, optional provider/orientation/minimum width/licence policy | Candidate previews, dimensions, creator, licence, credit, `search_id` |
| `stock_image_download` | `project_id`, `search_id`, chosen `candidate_id`, optional `scene_id` | Local image, provenance and credit sidecars, schema-compatible asset-manifest entry |

Discover and call them through the standard Content Factory operation tools.
Search is available in research, scene planning and asset stages; download is
available in the asset stage. Existing project approvals and network policy
remain in force. The calling AI chooses the photograph and updates the asset
manifest after visual review.

| Provider | Credentials | Licence handling |
|---|---|---|
| Wikimedia Commons (default) | None | Explicit CC0, public-domain mark, CC BY, CC BY-SA |
| Openverse | None for anonymous search | Same CC allowlist; original source checked on download |
| Pexels | Administrator-configured free API key | Pexels licence; preserve photographer and Pexels API credits |
| Pixabay | Administrator-configured free API key | Pixabay Content License; preserve source links |

Use `license_policy: public_domain` to restrict results to CC0/public-domain
marks (custom Pexels/Pixabay licences do not qualify). Unknown, NC and ND
licences are excluded. API quotas apply. Pexels may restrict issuance of new
API keys; the two keyless providers remain usable.
Pixabay API responses are cached per project for 24 hours as required by its
API terms; a repeated identical query reuses that response.

Downloads accept static JPEG/PNG/WebP only, bound network bytes and pixel
count, and use the public-HTTPS client with DNS pinning and redirect checks.
Files stay inside project assets, existing different content is not
overwritten, and search receipts expire after 24 hours. Each image receives
`.source.json` (source, creator, licence URL, retrieved time, checksum) and
`.credit.txt`. Credentials are never stored in the receipt. Images from remote
sources can disappear or change; repeat the search on a failed download.

Free does not mean unrestricted. Check the original source, required public
credits, share-alike conditions and any people/property/brand restrictions.
The sidecars preserve evidence; they do not constitute rights clearance.

Provider references: [Commons reuse](https://commons.wikimedia.org/wiki/Commons:Reusing_content_outside_Wikimedia/en),
[Openverse API](https://api.openverse.org/v1/),
[Pexels API](https://www.pexels.com/api/documentation/),
[Pixabay API](https://pixabay.com/api/docs/).
