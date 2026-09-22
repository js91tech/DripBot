import * as cheerio from "cheerio";
import type { DataSource, PlatformTrend } from "@/lib/types";

const FETCH_MS = 4000;

async function fetchWithTimeout(url: string) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), FETCH_MS);
  try {
    const response = await fetch(url, {
      signal: controller.signal,
      headers: { "User-Agent": "CommercePulse/1.0 (research bot; +https://localhost)" },
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return await response.text();
  } finally {
    clearTimeout(timer);
  }
}

export async function fetchNewsHeadlines(query: string): Promise<{
  headlines: string[];
  source?: DataSource;
}> {
  try {
    const url = `https://news.google.com/rss/search?q=${encodeURIComponent(
      `${query} product market`
    )}&hl=en-US&gl=US&ceid=US:en`;
    const xml = await fetchWithTimeout(url);
    const $ = cheerio.load(xml, { xmlMode: true });
    const headlines = $("item > title")
      .toArray()
      .slice(0, 5)
      .map((el) => $(el).text().trim())
      .filter(Boolean);
    if (!headlines.length) return { headlines: [] };
    return {
      headlines,
      source: {
        name: "Google News RSS",
        type: "live",
        detail: `${headlines.length} public headlines`,
      },
    };
  } catch {
    return { headlines: [] };
  }
}

export async function fetchSerpShopping(query: string): Promise<{
  listings: string[];
  source?: DataSource;
}> {
  const key = process.env.SERPAPI_KEY;
  if (!key) return { listings: [] };
  try {
    const url = `https://serpapi.com/search.json?engine=google_shopping&q=${encodeURIComponent(
      query
    )}&api_key=${encodeURIComponent(key)}&num=8`;
    const json = JSON.parse(await fetchWithTimeout(url)) as {
      shopping_results?: { title?: string }[];
    };
    const listings =
      json.shopping_results
        ?.map((item) => item.title?.trim())
        .filter((title): title is string => Boolean(title))
        .slice(0, 6) ?? [];
    if (!listings.length) return { listings: [] };
    return {
      listings,
      source: {
        name: "SerpAPI Google Shopping",
        type: "live",
        detail: `${listings.length} shopping results`,
      },
    };
  } catch {
    return { listings: [] };
  }
}

export function mergeLiveListings(platforms: PlatformTrend[], listings: string[]) {
  if (!listings.length) return platforms;
  return platforms.map((platform) =>
    platform.platform === "Amazon" || platform.platform === "Google Trends"
      ? { ...platform, sampleListings: [...listings.slice(0, 3), ...platform.sampleListings].slice(0, 4) }
      : platform
  );
}
