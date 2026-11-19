# Playable media and downloads

Use the same project id and relative asset path returned by production:

```json
{
  "project_id": "my-video",
  "relative_path": "assets/voice-sample.wav",
  "mode": "link"
}
```

Pass this to `factory_export_media`. Remote MCP returns `download_url`, MIME
type, filename, byte size, SHA-256 and a five-minute expiry. The URL is a scoped
bearer link: anyone holding it can access that one file until it expires. The
route supports byte ranges and inline audio/video playback. No Backlot port or
workspace folder needs to be made public. Call the tool again for a fresh link.
`factory_outputs` also includes links for media files, so clients with an older
cached tool list can use their existing listing tool immediately.

On stdio, or when a client cannot open a link, request `mode: "bytes"`. The result
contains a bounded base64 chunk. Decode it locally and append the decoded bytes,
then repeat using `next_offset` and `expected_sha256` from the first result.
Stop when `next_offset` is null. Verify the final SHA-256. Default chunks are
196,608 bytes; the maximum is 262,144 bytes. These limits avoid putting a large
video into an LLM context. Use link mode for normal video downloads.

Only supported media under the project's `assets/` and `renders/` directories
can be exported. Traversal, paths outside the project and escaping symlinks are
rejected. Model configs, credentials, databases and arbitrary project files are
not downloadable through this route.
