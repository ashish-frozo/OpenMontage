# Creator trend analytics

Four MCP tools: factory_trend_collect, factory_trend_snapshots,
factory_trend_label, factory_trend_report. Data persists on the MCP host in
.runtime/creator-trends.sqlite3 and survives service restarts.

YouTube supports topic search, limited regional mostPopular charts, and explicit
video-id cohorts through the connected YouTube Composio account. Search uses a
rolling publication lookback and a bounded top-viewed sample (25 maximum).
Refresh a fixed cohort with the same video_ids for the cleanest growth comparison.
Region is a selection/viewability parameter; it does not reveal viewer geography.

Instagram owned mode supports eligible Business/Creator media and batched
insights. Ineligible batches fall back to public metadata with a warning, keeping
views null. public_watchlist mode samples selected handles via the connected
ScrapeCreators provider; it may incur credits. Provider coverage is not a global
Instagram trend feed. Maximum three handles, 25 retained videos per snapshot.
Calls do not publish, modify platform content, or upload video files.

A snapshot is not growth. Repeat the same scope after at least an hour. Reports
compare cumulative counters for matching video IDs and metric definitions,
exclude negative counter corrections from growth, and retain missing values.
Topic/style groups need three videos with growth and two distinct creators to
receive the sampled_growth label; that remains observational, not causal.
The caller supplies interpretations with evidence. Style labels require visual
review. Reports include evidence video IDs, sample coverage and source URLs.
Do not add YouTube and Instagram view counts or compare incompatible definitions.
Owned channel CTR, retention and traffic-source attribution require account
analytics permissions and are separate from these public trend observations.

Example collect arguments:
```json
{"platform":"youtube","query":"AI video generation","region":"IN","lookback_days":7,"limit":20}
```
Use the returned id as snapshot_id in factory_trend_label and factory_trend_report.
For public Instagram use platform=instagram, instagram_mode=public_watchlist,
handles=["example_creator"]. Account refers to ScrapeCreators for this mode;
it refers to Instagram for owned mode and YouTube for YouTube collection.

API references: https://developers.google.com/youtube/data/reference/rest/v3/videos/list
and https://developers.facebook.com/docs/insights/overview/ .
