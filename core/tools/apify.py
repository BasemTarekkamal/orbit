#!/usr/bin/env python3
"""staff-apify: the only way an employee reaches Apify's scrapers (TikTok, Instagram, Facebook, X,
YouTube, LinkedIn, Reddit, Google Maps, Google Search/News/Trends, Meta Ad Library, Amazon...).

    staff-apify list                              the vetted catalog: alias, what it gets, cost
    staff-apify schema <alias>                    the actor's live input fields (free metadata call)
    staff-apify run <alias> '<json>' [--max-items N] [--max-usd X] [--tag slug] [--wait S]
    staff-apify run <alias> @inputs/x.json        input from a JSON file in your workspace
    staff-apify results <run-id>                  collect a run that was still going when run returned
    staff-apify budget                            this month's spend, per-run cap, recent runs
    staff-apify verify                            (owner) re-check every catalog actor exists and is
                                                  maintained, using Apify's free public metadata

Why a gateway: Apify spends real money and its actors touch the open web. This runs outside the
sandbox (it alone reads the token, ~/Staff/.secrets/apify_token) and enforces:
  * a vetted catalog only: no arbitrary actors;
  * input sanitising: no webhooks, connectors, "deliver to" or MCP fields (nothing sends data
    anywhere else), no cookies/logins/headers/proxy overrides/custom code, no paid lead/email
    enrichment, reviewers' personal data off, crawlers stay on robots.txt; URL objects reduced to
    {"url"} (GET only); per-actor item limits clamped to --max-items;
  * a per-run cost cap (Apify's maxTotalChargeUsd, plus memory/timeout limits for compute) and a
    monthly budget for the whole account, shared by all employees (state in ~/Staff/state):
    settings come from the owner's settings (key "apify": monthly_budget_usd, default 5;
    max_run_usd, default 0.5; hard maximum 2 per run). Over budget = refused, ask the owner;
  * results only into <workspace>/research/scrapes/<date>-<alias>-<tag>.json.

Start small (--max-items 10), check the output, then scale. If a run returns 0 items, run
`schema <alias>` and fix the input; max 3 tries. Run it as ONE plain command (no pipes, redirects,
&&, ; or $(...)), or it runs inside the sandbox and fails.
Python 3.9+, needs requests.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import _kit  # noqa: E402

try:
    import fcntl  # noqa: E402
except ImportError:  # pragma: no cover
    fcntl = None

API = "https://api.apify.com/v2"
HARD_MAX_RUN_USD = 2.0
DEFAULT_MONTHLY_USD = 5.0
DEFAULT_RUN_USD = 0.5
HARD_MAX_ITEMS = 1000
CU_PRICE_USD = 0.4            # conservative compute-unit price used to bound free actors' runtime
DEFAULT_WAIT_S = 100          # under the agent's default 2-minute Bash timeout
TERMINAL = ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT")

# Any user-supplied input key matching this is dropped: things that send data elsewhere, log in,
# inject code or headers, pick proxies, or buy enrichment from data brokers.
STRIP_KEYS = re.compile(r"webhook|connector|deliver|^mcp|callback|notif|cookie|proxy|function|hook|header|"
                        r"password|passw|secret|token|api_?key|apikey|^login|credential|enrich|kvstore|"
                        r"keyvaluestore|datasetname|^storage", re.I)

# The catalog. Every actor id was checked against Apify's public metadata (GET /v2/acts/<id>) on
# 2026-10-29: exists, not deprecated, updated within the last 2 months unless noted, high 30-day
# success rate. `verified` records what we saw; `cost` is the store's pay-per-event price for the
# free tier (paid plans pay less). Re-check with `staff-apify verify`.
#   defaults: merged under the user's input        force: always set, the user can't change
#   deny: user keys dropped (paid add-ons, privacy) limits: numeric keys clamped to --max-items
#   urls: list fields whose items become {"url": ...}  needs: at least one must be non-empty
#   show: fields printed per item (dotted paths)   min_cap: actor's minimum maxTotalChargeUsd
CATALOG = {
    "google-search": dict(
        actor="apify/google-search-scraper",
        what="Google results for one or many queries (newline-separated), any language/country; site:, "
             "filetype:, date filters. Organic results, People Also Ask, related queries.",
        cost="$0.0045 per results page (10 results); AI-chatbot add-ons blocked",
        verified="26k users/30d, 4.6 stars, 98% runs ok",
        defaults={"maxPagesPerQuery": 1, "countryCode": "", "searchLanguage": "", "languageCode": ""},
        deny=["aiModeSearch", "perplexitySearch", "chatGptSearch", "copilotSearch", "geminiSearch", "linkProspecting"],
        limits=[], needs=["queries"], join=["queries"], items=10, min_cap=0.5,
        show=["searchQuery.term"]),
    "crawl": dict(
        actor="apify/website-content-crawler",
        what="Clean, LLM-ready markdown from given URLs or a whole site section (follows links). "
             "crawlerType cheerio (default, cheap) or playwright:adaptive for JS sites.",
        cost="no actor fee: compute only (cheerio is cheapest; browser modes cost several times more); "
             "bounded by memory/timeout",
        verified="14k users/30d, 4.6 stars, 96% runs ok",
        defaults={"crawlerType": "cheerio", "maxCrawlPages": 10, "maxCrawlDepth": 2, "saveMarkdown": True,
                  "removeCookieWarnings": True, "blockMedia": True, "proxyConfiguration": {"useApifyProxy": True}},
        force={"respectRobotsTxtFile": True, "saveFiles": False, "saveScreenshots": False, "summarize": False,
               "saveHtmlAsFile": False},
        deny=["initialCookies", "customHttpHeaders", "signHttpRequests", "pageFunction"],
        limits=["maxCrawlPages", "maxResults"], urls=["startUrls"], needs=["startUrls"], items=10,
        memory=4096, timeout=600, show=["metadata.title", "url", "text"]),
    "rag-browser": dict(
        actor="apify/rag-web-browser",
        what="A search query OR one URL -> the top pages as markdown in one call. Set scrapingTool "
             "browser-playwright for JS pages (e.g. Facebook reel/share links).",
        cost="$0.0035 per search + $0.0023 per page fetched",
        verified="33k users/30d, 4.7 stars, 99% runs ok",
        defaults={"maxResults": 3, "outputFormats": ["markdown"], "scrapingTool": "raw-http"},
        limits=["maxResults"], needs=["query"], items=5,
        show=["metadata.title", "metadata.url", "markdown"]),
    "google-news": dict(
        actor="data_xplorer/google-news-scraper-fast",
        what="Google News articles for keywords or topics, by region:language (e.g. US:en, EG:ar, FR:fr, "
             "MX:es-419) and timeframe (1h..1y). decodeUrls gives publisher URLs.",
        cost="$0.004 per article",
        verified="600 users/30d, 4.9 stars, 99% runs ok (chosen over lhotanova/google-news-scraper, 200 users)",
        defaults={"maxArticles": 20, "timeframe": "7d", "region_language": "US:en", "decodeUrls": True,
                  "extractDescriptions": False, "extractImages": False},
        limits=["maxArticles"], needs=["keywords", "topics", "topicUrls"], items=20,
        show=["title", "source", "publishedAt", "date", "link", "url"]),
    "google-trends": dict(
        actor="data_xplorer/google-trends-fast-scraper",
        what="Google Trends interest over time (+ related queries, regions) for ONE search term per run; "
             "mode 'trending' for what is trending now in a country.",
        cost="$0.025 per run + $0.002 per item",
        verified="850 users/30d, 4.9 stars, 99% runs ok (apify/google-trends-scraper had 56% ok runs)",
        defaults={"mode": "keyword", "predefinedTimeframe": "today 12-m", "geo": "", "fetchRegionalData": False},
        limits=["trendingSearchesMaxItems"], needs=["keyword", "trendingSearchesCountry"], items=20, show=["keyword", "date", "value"]),
    "maps-places": dict(
        actor="compass/crawler-google-places",
        what="Google Maps businesses for search terms in a place: name, category, address, phone, website, "
             "rating, review count, hours, coordinates, Maps URL. scrapeContacts adds emails/socials from "
             "their website.",
        cost="$0.004 per place; +$0.002 per place with scrapeContacts; reviews +$0.0005 each",
        verified="46k users/30d, 4.7 stars, 96% runs ok",
        defaults={"maxCrawledPlacesPerSearch": 20, "language": "en", "scrapeContacts": False, "maxReviews": 0,
                  "maxImages": 0, "maxQuestions": 0},
        force={"scrapeReviewsPersonalData": False, "scrapeImageAuthors": False, "enableCompetitorAnalysis": False},
        deny=["scrapeSocialMediaProfiles", "maxCompetitorsToAnalyze", "allPlacesNoSearchAction"],
        limits=["maxCrawledPlacesPerSearch", "maxReviews", "maxImages", "maxQuestions"], urls=["startUrls"],
        needs=["searchStringsArray", "startUrls", "placeIds"], items=20, min_cap=0.5,
        show=["title", "categoryName", "address", "phone", "website", "totalScore", "reviewsCount", "url"]),
    "maps-reviews": dict(
        actor="compass/google-maps-reviews-scraper",
        what="Reviews of given Google Maps places (URLs or place IDs): stars, text, date, owner replies. "
             "Reviewer names/photos are switched off.",
        cost="$0.0006 per review",
        verified="9k users/30d, 4.9 stars, 100% runs ok",
        defaults={"maxReviews": 50, "reviewsSort": "newest", "language": "en"},
        force={"personalData": False}, limits=["maxReviews"], urls=["startUrls"],
        needs=["startUrls", "placeIds"], items=50,
        show=["title", "stars", "publishedAtDate", "text", "responseFromOwnerText"]),
    "contact-info": dict(
        actor="vdrmota/contact-info-scraper",
        what="Business contact details published on given websites: emails, phones, social profiles "
             "(stays on each site's own domain). Business sites only, not people.",
        cost="$0.002 per page crawled; lead/social enrichment blocked",
        verified="3.9k users/30d, 4.2 stars, 97% runs ok",
        defaults={"maxRequestsPerStartUrl": 10, "maxDepth": 1, "mergeContacts": True, "useBrowser": False,
                  "proxyConfig": {"useApifyProxy": True}},
        force={"sameDomain": True}, deny=["scrapeSocialMediaProfiles"],
        limits=["maxRequestsPerStartUrl", "maxRequests"], urls=["startUrls"], needs=["startUrls"], items=20,
        show=["domain", "emails", "phones", "facebooks", "instagrams", "linkedIns"]),
    "youtube": dict(
        actor="streamers/youtube-scraper",
        what="YouTube search results, channels or video URLs: title, channel, views, likes, date, "
             "duration, description. transcriptionAndSubtitle ALWAYS_SUBTITLES adds the captions.",
        cost="$0.004 per video; AI transcription of videos without captions +$0.048 per minute",
        verified="16k users/30d, 4.8 stars, 99% runs ok",
        defaults={"maxResults": 10, "maxResultsShorts": 0, "maxResultStreams": 0, "transcriptionAndSubtitle": "NONE",
                  "subtitlesLanguage": "any", "subtitlesFormat": "plaintext"},
        deny=["aiVideoDescription", "aiVideoSummary"], limits=["maxResults", "maxResultsShorts", "maxResultStreams"],
        urls=["startUrls"], needs=["searchQueries", "startUrls"], items=10,
        show=["title", "channelName", "viewCount", "date", "url"]),
    "youtube-transcript": dict(
        actor="karamelo/youtube-transcripts",
        what="Transcripts of YouTube videos/Shorts (urls: one or many), in the video's caption language; "
             "outputFormat singleStringText (default here), textWithTimestamps or captions.",
        cost="$0.007 per video",
        verified="865 users/30d, 5.0 stars, 100% runs ok (starvibe/youtube-video-transcript not updated since 2026-03)",
        defaults={"outputFormat": "singleStringText", "channelNameBoolean": True, "datePublishedBoolean": True,
                  "viewCountBoolean": True},
        needs=["urls"], items=10, show=["title", "channelName", "datePublished", "captions"]),
    "tiktok": dict(
        actor="clockworks/tiktok-scraper",
        what="TikTok videos by URL (postURLs), profiles, hashtags or searchQueries: caption, plays, likes, "
             "shares, author, date, music, subtitles, comments (commentsPerPost).",
        cost="$0.0037 per video, +$0.00125 per comment; transcribing videos without subtitles +$0.048 per "
             "started minute (downloadSubtitlesOptions DOWNLOAD_AND_TRANSCRIBE_VIDEOS_WITHOUT_SUBTITLES)",
        verified="32k users/30d, 4.7 stars, 98% runs ok",
        defaults={"resultsPerPage": 10, "downloadSubtitlesOptions": "DOWNLOAD_SUBTITLES", "commentsPerPost": 0},
        force={"shouldDownloadVideos": False, "shouldDownloadCovers": False, "shouldDownloadSlideshowImages": False,
               "shouldDownloadAvatars": False, "shouldDownloadMusicCovers": False},
        deny=["maxFollowersPerProfile", "maxFollowingPerProfile", "aiVideoDescription", "aiVideoSummary"],
        limits=["resultsPerPage", "commentsPerPost", "topLevelCommentsPerPost", "maxRepliesPerComment",
                "maxProfilesPerQuery"], needs=["postURLs", "profiles", "hashtags", "searchQueries"], items=10,
        min_cap=0.5, show=["authorMeta.name", "text", "playCount", "diggCount", "createTimeISO", "webVideoUrl"]),
    "instagram": dict(
        actor="apify/instagram-scraper",
        what="Public Instagram: profiles (resultsType details), posts, reels, comments (/p/ URLs), "
             "mentions, or search hashtags/profiles/places. Logged-out view.",
        cost="$0.0027 per result",
        verified="61k users/30d, 4.7 stars, 100% runs ok",
        defaults={"resultsType": "posts", "resultsLimit": 10, "searchLimit": 5},
        limits=["resultsLimit", "searchLimit"], needs=["directUrls", "search"], items=10,
        show=["ownerUsername", "username", "caption", "text", "likesCount", "commentsCount", "followersCount",
              "timestamp", "url"]),
    "facebook-page": dict(
        actor="apify/facebook-pages-scraper",
        what="Public Facebook PAGE info: name, category, followers, likes, phone, email, website, address, "
             "intro. Page URLs only (reel/share/post links are rejected: see the social-media skill).",
        cost="$0.012 per page",
        verified="8.4k users/30d, 4.7 stars, 100% runs ok",
        defaults={}, urls=["startUrls"], needs=["startUrls"], items=10,
        show=["title", "categories", "followers", "likes", "phone", "email", "website", "address", "pageUrl"]),
    "facebook-posts": dict(
        actor="apify/facebook-posts-scraper",
        what="Posts of public Facebook pages/profiles: text, date, likes, comments and shares counts, "
             "media, link. Date filters onlyPostsNewerThan / OlderThan.",
        cost="$0.005 per post + $0.001 per run",
        verified="18k users/30d, 4.7 stars, 100% runs ok",
        defaults={"resultsLimit": 10, "captionText": False}, limits=["resultsLimit"], urls=["startUrls"],
        needs=["startUrls"], items=10, show=["pageName", "time", "text", "likes", "comments", "shares", "url"]),
    "facebook-comments": dict(
        actor="apify/facebook-comments-scraper",
        what="Comments under public Facebook posts or reels (post URLs): text, date, likes, replies count.",
        cost="$0.0025 per comment + $0.001 per run",
        verified="5k users/30d, 4.8 stars, 100% runs ok",
        defaults={"resultsLimit": 30, "includeNestedComments": False, "viewOption": "RANKED_UNFILTERED"},
        limits=["resultsLimit"], urls=["startUrls"], needs=["startUrls"], items=30,
        show=["date", "text", "likesCount", "facebookUrl"]),
    "fb-ads": dict(
        actor="apify/facebook-ads-scraper",
        what="Meta Ad Library: ads for an Ad Library search URL (any country/keyword) or a Facebook page: "
             "advertiser, ad text, start date, platforms, landing link; includeAboutPage for page info.",
        cost="$0.0058 per ad (e-commerce enrichment blocked)",
        verified="10k users/30d, 4.0 stars, 99% runs ok",
        defaults={"resultsLimit": 20, "includeAboutPage": False, "isDetailsPerAd": False, "onlyTotal": False},
        limits=["resultsLimit"], urls=["startUrls"], needs=["startUrls"], items=20,
        show=["pageName", "startDateFormatted", "snapshot.body.text", "snapshot.linkUrl", "adArchiveID"]),
    "x": dict(
        actor="apidojo/tweet-scraper",
        what="X/Twitter posts by searchTerms (full advanced-search syntax: from:, since:, lang:, min_faves:), "
             "twitterHandles, tweet/list URLs or conversationIds: text, date, likes, reposts, views, author.",
        cost="$0.0004 per tweet ($0.40 per 1,000)",
        verified="10k users/30d, 3.9 stars, 99% runs ok",
        defaults={"maxItems": 20, "sort": "Latest"}, limits=["maxItems"],
        needs=["searchTerms", "twitterHandles", "startUrls", "conversationIds"], items=20,
        show=["author.userName", "createdAt", "text", "likeCount", "retweetCount", "viewCount", "url"]),
    "threads": dict(
        actor="futurizerush/meta-threads-scraper",
        what="Threads (Meta): mode user (usernames' posts), search (keywords), profiles (find accounts), "
             "post_link (a post + its thread). No login.",
        cost="$0.02 per run + $0.0025 per post",
        verified="1.9k users/30d, 4.2 stars, 98% runs ok",
        defaults={"mode": "user", "max_posts": 20}, limits=["max_posts"],
        needs=["usernames", "keywords", "post_links"], items=20,
        show=["username", "created_at", "text", "like_count", "reply_count", "url", "post_url"]),
    "linkedin-company": dict(
        actor="harvestapi/linkedin-company",
        what="Public LinkedIn COMPANY pages by URL or name search: website, industry, size, HQ, locations, "
             "followers, founded, description, specialties. No cookies or account. Never people profiles.",
        cost="$0.004 per company",
        verified="7.7k users/30d, 4.5 stars, 100% runs ok",
        defaults={}, needs=["companies", "searches"], items=10,
        show=["name", "website", "industry", "employeeCount", "followerCount", "headquarter", "linkedinUrl"]),
    "reddit": dict(
        actor="harshmaur/reddit-scraper",
        what="Reddit posts/comments by searchTerms (optionally withinCommunity), subreddit or post URLs: "
             "title, text, score, comments, subreddit, date. Reddit's robots.txt blocks direct fetching.",
        cost="$0.02 per run + $0.002 per item",
        verified="5.2k users/30d, 4.5 stars, 98% runs ok (trudax/reddit-scraper-lite had 87% ok runs)",
        defaults={"searchPosts": True, "searchComments": False, "searchSort": "relevance", "searchTime": "year",
                  "crawlCommentsPerPost": False, "maxPostsCount": 10, "maxCommentsCount": 20,
                  "maxCommentsPerPost": 20, "maxCommunitiesCount": 2},
        force={"includeNSFW": False}, limits=["maxPostsCount", "maxCommentsCount", "maxCommentsPerPost",
                                              "maxCommunitiesCount"],
        urls=["startUrls"], needs=["searchTerms", "startUrls", "subredditUrls"], items=20,
        show=["communityName", "title", "body", "upVotes", "numberOfComments", "createdAt", "url"]),
    "amazon-reviews": dict(
        actor="junglee/amazon-reviews-scraper",
        what="Reviews of Amazon products (any Amazon domain): rating, title, text, date, verified, "
             "variant. Reviewer personal data off.",
        cost="$0.006 per review",
        verified="2.4k users/30d, 4.1 stars, 96% runs ok",
        defaults={"maxReviews": 20, "sort": "recent"}, force={"includeGdprSensitive": False},
        limits=["maxReviews"], urls=["productUrls"], needs=["productUrls"], items=20,
        show=["ratingScore", "reviewTitle", "reviewDescription", "date", "isVerified"]),
}
ALIASES = {"search": "google-search", "fetch": "rag-browser", "places": "maps-places", "news": "google-news",
           "trends": "google-trends", "tweets": "x", "twitter": "x", "transcript": "youtube-transcript",
           "facebook": "facebook-page"}


# ---------------------------------------------------------------------------------------------
# Settings, budget and the shared spend ledger


def settings() -> dict:
    cfg = (_kit.config() or {}).get("apify") or {}

    def num(key, default):
        try:
            v = float(cfg.get(key, default))
            return v if v >= 0 else default
        except (TypeError, ValueError):
            return default
    return {"monthly": num("monthly_budget_usd", DEFAULT_MONTHLY_USD),
            "max_run": min(num("max_run_usd", DEFAULT_RUN_USD), HARD_MAX_RUN_USD)}


def ledger_path() -> str:
    return os.path.join(_kit.HOME, "state", "apify_spend.json")


class Ledger:
    """apify_spend.json, locked while read-modified-written (several employees share it)."""

    def __enter__(self):
        p = ledger_path()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        self.fh = open(p, "a+", encoding="utf-8")
        if fcntl is not None:
            fcntl.flock(self.fh, fcntl.LOCK_EX)
        self.fh.seek(0)
        try:
            self.data = json.loads(self.fh.read() or "{}")
        except ValueError:
            self.data = {}
        if not isinstance(self.data, dict):
            self.data = {}
        self.data.setdefault("runs", [])
        return self

    def save(self):
        self.fh.seek(0)
        self.fh.truncate()
        self.fh.write(json.dumps(self.data, ensure_ascii=False, indent=1))
        self.fh.flush()

    def __exit__(self, *exc):
        if fcntl is not None:
            fcntl.flock(self.fh, fcntl.LOCK_UN)
        self.fh.close()


def month() -> str:
    return time.strftime("%Y-%m")


def month_spend(data: dict, m: str = None):
    """(final spend, pending reservations) this month. A run still in flight counts at its full cap."""
    m = m or month()
    spent = pending = 0.0
    for r in data.get("runs", []):
        if r.get("month") != m:
            continue
        if r.get("cost_usd") is not None:
            spent += float(r["cost_usd"])
        else:
            pending += float(r.get("reserved_usd") or 0)
    return round(spent, 4), round(pending, 4)


# ---------------------------------------------------------------------------------------------
# HTTP (tests replace _http)


def token():
    return _kit.secret("apify_token")


def _http(method: str, path: str, params: dict = None, body=None, auth: bool = True, timeout: int = 90):
    """One call to the Apify API. Returns parsed JSON. Raises RuntimeError with Apify's message."""
    import fetch  # the guarded session: public addresses only, no proxies from the environment
    import requests
    headers = {"Accept": "application/json"}
    if auth:
        tok = token()
        if not tok:
            raise RuntimeError("no Apify token. Ask your owner to add their Apify API token (Apify console -> "
                               "Settings -> API & Integrations) in the control panel; it is saved as "
                               "~/Staff/.secrets/apify_token. The free Apify plan includes monthly credit.")
        headers["Authorization"] = "Bearer " + tok
    url = API + path
    fetch.check_url(url)
    try:
        r = fetch.session().request(method, url, params=params or None, json=body, headers=headers,
                                    timeout=(10, timeout), allow_redirects=False)
    except requests.exceptions.RequestException as e:
        raise RuntimeError("couldn't reach Apify (%s)" % str(e)[:200])
    try:
        data = r.json() if r.content else {}
    except ValueError:
        data = {"raw": r.text[:300]}
    if r.status_code >= 400:
        err = data.get("error") if isinstance(data, dict) else None
        msg = err.get("message") if isinstance(err, dict) else str(data)[:300]
        raise RuntimeError("Apify said HTTP %s: %s" % (r.status_code, msg))
    return data


# ---------------------------------------------------------------------------------------------
# Input sanitising


def resolve(alias: str) -> str:
    a = (alias or "").strip().lower()
    a = ALIASES.get(a, a)
    if a in CATALOG:
        return a
    for k, v in CATALOG.items():
        if v["actor"].lower() == a or v["actor"].lower().replace("/", "~") == a:
            return k
    raise ValueError("'%s' is not in the vetted catalog. Allowed: %s. (No arbitrary actors: ask your owner "
                     "if you need another one added.)" % (alias, ", ".join(CATALOG)))


def _clean_value(v, dropped: list, path: str):
    if isinstance(v, dict):
        out = {}
        for k, x in v.items():
            if STRIP_KEYS.search(str(k)):
                dropped.append(path + str(k))
                continue
            out[k] = _clean_value(x, dropped, path + str(k) + ".")
        return out
    if isinstance(v, list):
        return [_clean_value(x, dropped, path) for x in v]
    return v


def _as_url_objects(v, key: str, dropped: list):
    items = v if isinstance(v, list) else [v]
    out = []
    for it in items:
        u = it.get("url") if isinstance(it, dict) else it
        if isinstance(it, dict) and set(it) - {"url"}:
            dropped.append("%s[].%s" % (key, ",".join(sorted(set(it) - {"url"}))))
        if not isinstance(u, str) or not re.match(r"^https?://", u.strip(), re.I):
            raise ValueError("%s needs http(s) URLs, got %r" % (key, u))
        out.append({"url": u.strip()})
    return out


def build_input(alias: str, user: dict, max_items: int):
    """(actor input, dropped keys, notes). Raises ValueError on unusable input."""
    spec = CATALOG[alias]
    if not isinstance(user, dict):
        raise ValueError("input must be a JSON object, e.g. %s" % json.dumps(example_input(alias)))
    dropped, notes = [], []
    clean = {}
    for k, v in user.items():
        if STRIP_KEYS.search(str(k)) or k in spec.get("deny", []):
            dropped.append(k)
            continue
        clean[k] = _clean_value(v, dropped, k + ".")
    for k in spec.get("urls", []):
        if k in clean:
            clean[k] = _as_url_objects(clean[k], k, dropped)
    for k in spec.get("join", []):
        if isinstance(clean.get(k), list):
            clean[k] = "\n".join(str(x) for x in clean[k])
    inp = json.loads(json.dumps(spec.get("defaults", {})))
    inp.update(clean)
    for k, v in spec.get("force", {}).items():
        if k in user and user[k] != v:
            notes.append("%s is fixed to %s by the gateway" % (k, json.dumps(v)))
        inp[k] = v
    for k in spec.get("limits", []):
        if k in inp and isinstance(inp[k], (int, float)) and not isinstance(inp[k], bool) and inp[k] > max_items:
            notes.append("%s lowered from %s to %d (--max-items)" % (k, inp[k], max_items))
            inp[k] = max_items
    needs = spec.get("needs", [])
    if needs and not any(inp.get(k) not in (None, "", [], {}) for k in needs):
        raise ValueError("%s needs one of: %s. Example: %s" % (alias, ", ".join(needs),
                                                              json.dumps(example_input(alias), ensure_ascii=False)))
    return inp, dropped, notes


EXAMPLES = {
    "google-search": {"queries": "electric bikes market share 2026\nsite:example.gov e-bike subsidy", "countryCode": "us"},
    "crawl": {"startUrls": [{"url": "https://example.com/about"}], "maxCrawlPages": 5},
    "rag-browser": {"query": "https://www.facebook.com/share/r/XXXX/", "maxResults": 1,
                    "scrapingTool": "browser-playwright"},
    "google-news": {"keywords": ["solar subsidy"], "region_language": "US:en", "timeframe": "7d"},
    "google-trends": {"mode": "keyword", "keyword": "air fryer", "geo": "GB", "predefinedTimeframe": "today 5-y"},
    "maps-places": {"searchStringsArray": ["bakery"], "locationQuery": "Lyon, France", "maxCrawledPlacesPerSearch": 20},
    "maps-reviews": {"startUrls": [{"url": "https://www.google.com/maps/place/..."}], "maxReviews": 50},
    "contact-info": {"startUrls": [{"url": "https://example.com"}]},
    "youtube": {"searchQueries": ["home battery review"], "maxResults": 10},
    "youtube-transcript": {"urls": ["https://www.youtube.com/watch?v=VIDEO_ID"]},
    "tiktok": {"postURLs": ["https://www.tiktok.com/@user/video/123"], "commentsPerPost": 20},
    "instagram": {"directUrls": ["https://www.instagram.com/natgeo/"], "resultsType": "details"},
    "facebook-page": {"startUrls": [{"url": "https://www.facebook.com/SomePage/"}]},
    "facebook-posts": {"startUrls": [{"url": "https://www.facebook.com/SomePage/"}], "resultsLimit": 10},
    "facebook-comments": {"startUrls": [{"url": "https://www.facebook.com/SomePage/posts/123"}], "resultsLimit": 30},
    "fb-ads": {"startUrls": [{"url": "https://www.facebook.com/ads/library/?active_status=active&ad_type=all&country=US&q=meal%20kit&search_type=keyword_unordered"}]},
    "x": {"searchTerms": ["\"heat pump\" lang:en min_faves:20"], "maxItems": 20},
    "threads": {"mode": "search", "keywords": ["coffee subscription"], "max_posts": 20},
    "linkedin-company": {"companies": ["https://www.linkedin.com/company/example"]},
    "reddit": {"searchTerms": ["best budget espresso machine"], "maxPostsCount": 10},
    "amazon-reviews": {"productUrls": [{"url": "https://www.amazon.com/dp/B000000000"}], "maxReviews": 20},
}


def example_input(alias: str) -> dict:
    return EXAMPLES.get(alias, {})


# ---------------------------------------------------------------------------------------------
# Cost


def run_cost(run: dict, items_count: int = 0) -> float:
    """Upper estimate of what a finished run cost: pay-per-event charges + per-result fees + platform
    usage. (Errs high, so the budget is never overrun by our own arithmetic.)"""
    total = float(run.get("usageTotalUsd") or 0.0)
    pi = run.get("pricingInfo") or {}
    model = pi.get("pricingModel")
    if model == "PAY_PER_EVENT":
        events = ((pi.get("pricingPerEvent") or {}).get("actorChargeEvents")) or {}
        for ev, count in (run.get("chargedEventCounts") or {}).items():
            spec = events.get(ev) or {}
            price = spec.get("eventPriceUsd")
            if price is None:
                tiers = spec.get("eventTieredPricingUsd") or {}
                prices = [float(t.get("tieredEventPriceUsd") or 0) for t in tiers.values()]
                price = max(prices) if prices else 0.0
            total += float(price or 0) * float(count or 0)
    elif model == "PRICE_PER_DATASET_ITEM":
        total += float(pi.get("pricePerUnitUsd") or 0) * items_count
    return round(total, 4)


# ---------------------------------------------------------------------------------------------
# Commands


def _out(s: str = "") -> None:
    sys.stdout.write(s + "\n")


def _get(item, path: str):
    cur = item
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def _fmt(v) -> str:
    if isinstance(v, list):
        v = ", ".join(_fmt(x) for x in v[:5])
    elif isinstance(v, dict):
        v = json.dumps(v, ensure_ascii=False)
    return " ".join(str(v).split())


def brief(alias: str, item: dict) -> list:
    """One or more summary lines for one dataset item."""
    if alias == "google-search":
        rows = ["query: %s" % _fmt(_get(item, "searchQuery.term") or "?")]
        for r in (item.get("organicResults") or [])[:10]:
            rows.append("  %s | %s | %s" % (_fmt(r.get("title"))[:90], r.get("url"), _fmt(r.get("date") or "")[:12]))
        for r in (item.get("peopleAlsoAsk") or [])[:3]:
            rows.append("  PAA: %s" % _fmt(r.get("question"))[:120])
        return rows
    bits = []
    for path in CATALOG[alias].get("show", []):
        v = _get(item, path)
        if v in (None, "", [], {}):
            continue
        s = _fmt(v)
        bits.append(s[:220] if path.split(".")[-1] in ("text", "caption", "body", "markdown", "transcript_text",
                                                       "reviewDescription", "description") else s[:140])
    if not bits:
        for k in ("title", "name", "text", "url"):
            if item.get(k):
                bits.append(_fmt(item[k])[:160])
    if not bits:
        bits.append(json.dumps(item, ensure_ascii=False)[:240])
    return [" | ".join(bits)[:420]]


def _read_input(raw: str):
    raw = (raw or "").strip()
    if raw.startswith("@"):
        ws = os.path.realpath(_kit.workspace())
        path = os.path.realpath(os.path.join(ws, raw[1:]))
        if not (path == ws or path.startswith(ws + os.sep)):
            raise ValueError("input files must be inside your workspace (%s)" % ws)
        with open(path, encoding="utf-8") as fh:
            raw = fh.read()
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except ValueError as e:
        raise ValueError("input is not valid JSON (%s). Tip: write it to a file in your workspace and pass "
                         "@path/to/input.json" % e)


def cmd_list() -> int:
    s = settings()
    _out("Vetted Apify catalog (%d). Run: staff-apify run <alias> '<json>' --max-items 10. "
         "Budget: $%.2f/month, cap $%.2f/run." % (len(CATALOG), s["monthly"], s["max_run"]))
    for k, v in CATALOG.items():
        _out("%-19s %s" % (k, v["what"]))
        _out("%-19s   cost: %s | actor: %s" % ("", v["cost"], v["actor"]))
    return 0


def cmd_schema(alias: str) -> int:
    alias = resolve(alias)
    spec = CATALOG[alias]
    data = _http("GET", "/acts/%s/builds/default" % spec["actor"].replace("/", "~"), auth=False).get("data") or {}
    schema = data.get("inputSchema") or (data.get("actorDefinition") or {}).get("input") or {}
    if isinstance(schema, str):
        schema = json.loads(schema)
    deny, force = set(spec.get("deny", [])), spec.get("force", {})
    _out("%s (%s) input fields. Gateway defaults: %s" % (alias, spec["actor"], json.dumps(spec.get("defaults", {}),
                                                                                         ensure_ascii=False)))
    req = set(schema.get("required") or [])
    for k, v in (schema.get("properties") or {}).items():
        if v.get("editor") == "hidden":
            continue
        tag = ""
        if STRIP_KEYS.search(k) or k in deny:
            tag = "  [dropped by gateway]"
        elif k in force:
            tag = "  [fixed: %s]" % json.dumps(force[k])
        extra = ""
        if v.get("enum"):
            extra = " one of %s" % ",".join(str(x) for x in v["enum"][:10]) + ("..." if len(v["enum"]) > 10 else "")
        elif v.get("default") not in (None, "", [], {}):
            extra = " default %s" % json.dumps(v["default"], ensure_ascii=False)[:60]
        _out("  %-30s %-8s %s%s%s%s" % (k + ("*" if k in req else ""), v.get("type", ""),
                                       re.sub(r"<[^>]+>", "", v.get("title") or "")[:70], extra, tag, ""))
    _out("Example: staff-apify run %s '%s' --max-items 10" % (alias, json.dumps(example_input(alias), ensure_ascii=False)))
    return 0


def _save_result(alias: str, tag: str, record: dict) -> str:
    folder = _kit.out_dir("research", "scrapes")
    slug = re.sub(r"[^a-z0-9]+", "-", (tag or "").lower()).strip("-")[:40] or "run"
    path = os.path.join(folder, "%s-%s-%s.json" % (time.strftime("%Y%m%d-%H%M"), alias, slug))
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(record, fh, ensure_ascii=False, indent=1)
    return path


def _finish(entry_id: str, run: dict, alias: str, inp: dict, max_items: int, tag: str, notes: list) -> int:
    """Fetch the dataset of a finished run, settle its cost in the ledger, save, summarise."""
    items = []
    if run.get("defaultDatasetId"):
        got = _http("GET", "/datasets/%s/items" % run["defaultDatasetId"],
                    params={"clean": "true", "format": "json", "limit": max_items})
        items = got if isinstance(got, list) else []
    cost = run_cost(run, len(items))
    with Ledger() as lg:
        for r in lg.data["runs"]:
            if r.get("id") == entry_id:
                r.update(cost_usd=cost, status=run.get("status"), items=len(items), finished=time.strftime("%Y-%m-%dT%H:%M:%S"))
        lg.save()
        spent, pending = month_spend(lg.data)
    s = settings()
    path = _save_result(alias, tag, {"alias": alias, "actor": CATALOG[alias]["actor"], "run_id": run.get("id"),
                                     "status": run.get("status"), "cost_usd": cost, "input": inp,
                                     "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "items": items})
    _out("%s: %s, %d items, cost ~$%.3f (month: $%.2f of $%.2f%s) -> %s" % (
        alias, run.get("status"), len(items), cost, spent, s["monthly"],
        (", $%.2f pending" % pending) if pending else "", path))
    for n in notes:
        _out("Note: " + n)
    for it in items[:15]:
        for line in brief(alias, it if isinstance(it, dict) else {"value": it}):
            _out("- " + line if not line.startswith("  ") else line)
    if len(items) > 15:
        _out("... %d more items in the file (read it with the Read tool)" % (len(items) - 15))
    if not items:
        _out("0 items. Check the input against `staff-apify schema %s` before retrying (max 3 tries)." % alias)
    if run.get("status") != "SUCCEEDED":
        msg = run.get("statusMessage") or ""
        _out("The run ended %s%s." % (run.get("status"), (": " + msg[:200]) if msg else ""))
    return 0 if run.get("status") == "SUCCEEDED" else 1


def cmd_run(alias: str, raw: str, max_items=None, max_usd=None, tag=None, wait=None) -> int:
    alias = resolve(alias)
    spec = CATALOG[alias]
    s = settings()
    try:
        max_items = int(max_items) if max_items not in (None, "") else int(spec.get("items", 10))
        max_usd = float(max_usd) if max_usd not in (None, "") else s["max_run"]
        wait = int(wait) if wait not in (None, "") else DEFAULT_WAIT_S
    except ValueError:
        raise ValueError("--max-items, --max-usd and --wait take numbers")
    max_items = max(1, min(max_items, HARD_MAX_ITEMS))
    wait = max(10, min(wait, 540))
    if max_usd > s["max_run"]:
        raise ValueError("--max-usd %.2f is over the per-run cap of $%.2f set by your owner" % (max_usd, s["max_run"]))
    cap = max(max_usd, float(spec.get("min_cap") or 0))
    if cap > s["max_run"]:
        raise ValueError("%s needs a cost cap of at least $%.2f per run, above your owner's per-run cap of $%.2f. "
                         "Ask your owner to raise max_run_usd, or use a cheaper alias." % (alias, cap, s["max_run"]))
    inp, dropped, notes = build_input(alias, _read_input(raw), max_items)
    if dropped:
        notes.insert(0, "dropped input fields (not allowed through the gateway): %s" % ", ".join(sorted(set(dropped))))
    if not token():
        raise RuntimeError("no Apify token. Ask your owner to add their Apify API token in the control panel "
                           "(it is saved as ~/Staff/.secrets/apify_token).")
    entry_id = uuid.uuid4().hex[:12]
    with Ledger() as lg:
        spent, pending = month_spend(lg.data)
        if spent + pending + cap > s["monthly"] + 1e-9:
            raise PermissionError(
                "monthly Apify budget reached: $%.2f spent%s of $%.2f, and this run may cost up to $%.2f. "
                "Don't work around it: tell your owner what you want to run and why, and ask them to raise the "
                "monthly budget (Apify settings in the control panel) if it's worth it."
                % (spent, (" + $%.2f in flight" % pending) if pending else "", s["monthly"], cap))
        lg.data["runs"].append({"id": entry_id, "month": month(), "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                "employee": _kit.employee_id() or "owner", "alias": alias, "actor": spec["actor"],
                                "reserved_usd": cap, "cost_usd": None, "status": "STARTING", "max_items": max_items,
                                "tag": tag or "", "workspace": _kit.workspace()})
        lg.save()
    mem = spec.get("memory")
    timeout = int(spec.get("timeout", 300))
    if mem:   # bound compute for actors that bill platform usage: memory x time x CU price <= cap
        timeout = max(60, min(timeout, int(cap / (CU_PRICE_USD * mem / 1024.0) * 3600)))
    params = {"maxItems": max_items, "maxTotalChargeUsd": "%.2f" % cap, "timeout": timeout, "waitForFinish": 60}
    if mem:
        params["memory"] = mem
    try:
        run = _http("POST", "/acts/%s/runs" % spec["actor"].replace("/", "~"), params=params, body=inp,
                    timeout=90).get("data") or {}
    except Exception:
        with Ledger() as lg:   # nothing started: release the reservation
            lg.data["runs"] = [r for r in lg.data["runs"] if r.get("id") != entry_id]
            lg.save()
        raise
    with Ledger() as lg:
        for r in lg.data["runs"]:
            if r.get("id") == entry_id:
                r.update(run_id=run.get("id"), status=run.get("status"), input=inp)
        lg.save()
    sys.stderr.write("[staff-apify] started %s run %s (cap $%.2f, max %d items)\n" % (alias, run.get("id"), cap, max_items))
    t0 = time.time()
    while run.get("status") not in TERMINAL and time.time() - t0 < wait:
        left = int(wait - (time.time() - t0))
        run = _http("GET", "/actor-runs/%s" % run["id"], params={"waitForFinish": max(1, min(60, left))}).get("data") or run
    if run.get("status") not in TERMINAL:
        _out("%s run %s is still %s after %ds (cap $%.2f stays reserved). Collect it later with: "
             "staff-apify results %s" % (alias, run.get("id"), run.get("status"), wait, cap, run.get("id")))
        return 0
    return _finish(entry_id, run, alias, inp, max_items, tag, notes)


def cmd_results(run_id: str) -> int:
    with Ledger() as lg:
        entry = next((r for r in lg.data["runs"] if r.get("run_id") == run_id), None)
    if not entry:
        raise ValueError("run %s wasn't started through staff-apify on this Mac" % run_id)
    if entry.get("cost_usd") is not None:
        _out("run %s already collected (%s, $%.3f). Its file is in research/scrapes/." % (run_id, entry.get("status"),
                                                                                         entry["cost_usd"]))
        return 0
    run = _http("GET", "/actor-runs/%s" % run_id, params={"waitForFinish": 30}).get("data") or {}
    if run.get("status") not in TERMINAL:
        _out("run %s is still %s. Try again in a minute." % (run_id, run.get("status")))
        return 0
    return _finish(entry["id"], run, entry["alias"], entry.get("input") or {}, int(entry.get("max_items") or 10),
                   entry.get("tag") or "", [])


def cmd_budget() -> int:
    s = settings()
    with Ledger() as lg:
        spent, pending = month_spend(lg.data)
        runs = [r for r in lg.data["runs"] if r.get("month") == month()]
    left = max(0.0, s["monthly"] - spent - pending)
    _out("Apify %s: $%.2f spent%s of $%.2f -> $%.2f left. Per-run cap $%.2f (hard max $%.0f)." % (
        month(), spent, (" + $%.2f reserved by runs in flight" % pending) if pending else "", s["monthly"], left,
        s["max_run"], HARD_MAX_RUN_USD))
    if token():
        try:
            lim = _http("GET", "/users/me/limits").get("data") or {}
            cur = (lim.get("current") or {}).get("monthlyUsageUsd")
            mx = (lim.get("limits") or {}).get("maxMonthlyUsageUsd")
            if cur is not None:
                _out("Apify account (live): $%.2f used this billing cycle%s." % (float(cur), (" of $%.2f" % float(mx))
                                                                                if mx else ""))
        except Exception as e:  # noqa: BLE001
            _out("(couldn't read the live account usage: %s)" % str(e)[:120])
    else:
        _out("No Apify token yet: ask your owner to add one in the control panel.")
    for r in runs[-8:]:
        _out("  %s %-18s %-10s %s %s" % (r.get("at", "")[5:16], r.get("alias"), r.get("employee"),
                                         ("$%.3f" % r["cost_usd"]) if r.get("cost_usd") is not None else
                                         ("reserved $%.2f" % float(r.get("reserved_usd") or 0)), r.get("status")))
    return 0


def cmd_verify() -> int:
    """Re-check the catalog against Apify's public metadata (free, no token, never starts a run)."""
    bad = 0
    for alias, spec in CATALOG.items():
        try:
            d = _http("GET", "/acts/%s" % spec["actor"].replace("/", "~"), auth=False).get("data") or {}
        except RuntimeError as e:
            _out("%-19s MISSING  %s (%s)" % (alias, spec["actor"], e))
            bad += 1
            continue
        st = d.get("stats") or {}
        rs = st.get("publicActorRunStats30Days") or {}
        ok = 100.0 * rs.get("SUCCEEDED", 0) / max(1, rs.get("TOTAL", 0))
        flags = []
        if d.get("isDeprecated"):
            flags.append("DEPRECATED")
        if ok < 85:
            flags.append("LOW SUCCESS")
        if (d.get("modifiedAt") or "")[:7] < time.strftime("%Y-%m", time.gmtime(time.time() - 200 * 86400)):
            flags.append("STALE")
        bad += 1 if flags else 0
        _out("%-19s %-40s users30=%-6s rating=%.1f ok=%.0f%% updated=%s %s" % (
            alias, spec["actor"], st.get("totalUsers30Days"), st.get("actorReviewRating") or 0, ok,
            (d.get("modifiedAt") or "")[:10], " ".join(flags)))
    _out("%d of %d need attention." % (bad, len(CATALOG)))
    return 1 if bad else 0


def _opts(args: list):
    known = {"--max-items": None, "--max-usd": None, "--tag": None, "--wait": None}
    pos, i = [], 0
    while i < len(args):
        a = args[i]
        key, _, val = a.partition("=")
        if key in known:
            if not val:
                if i + 1 >= len(args):
                    raise ValueError("%s needs a value" % key)
                val = args[i + 1]
                i += 1
            known[key] = val
        else:
            pos.append(a)
        i += 1
    return pos, known


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help", "help"):
        _out(__doc__.strip())
        return 0 if args else 2
    _kit.require("apify")
    cmd = args[0]
    try:
        if cmd == "list":
            return cmd_list()
        if cmd == "budget":
            return cmd_budget()
        if cmd == "verify":
            return cmd_verify()
        if cmd == "schema":
            if len(args) < 2:
                raise ValueError("usage: staff-apify schema <alias>")
            return cmd_schema(args[1])
        if cmd == "results":
            if len(args) < 2:
                raise ValueError("usage: staff-apify results <run-id>")
            return cmd_results(args[1])
        if cmd == "run":
            pos, o = _opts(args[1:])
            if not pos:
                raise ValueError("usage: staff-apify run <alias> '<json input>' [--max-items N] [--max-usd X] [--tag slug]")
            if len(pos) > 2:
                raise ValueError("too many arguments: put the whole JSON input in single quotes, or in a file (@path)")
            return cmd_run(pos[0], pos[1] if len(pos) > 1 else "", o["--max-items"], o["--max-usd"], o["--tag"],
                           o["--wait"])
        raise ValueError("unknown command %r. Use: list | schema <alias> | run <alias> '<json>' | results <run-id> | "
                         "budget" % cmd)
    except PermissionError as e:
        sys.stderr.write("REFUSED: %s\n" % e)
        return 4
    except (ValueError, KeyError) as e:
        sys.stderr.write("INPUT: %s\n" % e)
        return 2
    except RuntimeError as e:
        sys.stderr.write("FAILED: %s\n" % e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
