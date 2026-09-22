import type { DataSource, Persona, ResearchResult } from "@/lib/types";
import { mockSummary } from "@/lib/mock-data";

function llmEnabled() {
  return Boolean(process.env.ANTHROPIC_API_KEY || process.env.OPENAI_API_KEY);
}

export async function enrichWithLlm(result: ResearchResult): Promise<{
  summary: string;
  personas: Persona[];
  usedLlm: boolean;
  source?: DataSource;
}> {
  if (!llmEnabled()) {
    return {
      summary: mockSummary(result),
      personas: result.personas,
      usedLlm: false,
    };
  }

  const prompt = `You are a dropshipping market analyst. Write a concise 120-word brief and refine 3 consumer personas for this product research.

Query: ${result.query}
Viability: ${result.viabilityScore}
Verdict: ${result.verdict}
Saturation: ${result.saturationRisk}
Predicted margin %: ${result.predictedMarginPct}
Recommended price: ${result.recommendedPriceMin}-${result.recommendedPriceMax}
Fulfillment: ${result.fulfillmentHint}

Return JSON only: {"summary": string, "personas": [{"name": string, "ageRange": string, "channels": string[], "motivation": string, "willingnessToPay": string}]}`;

  try {
    if (process.env.ANTHROPIC_API_KEY) {
      const Anthropic = (await import("@anthropic-ai/sdk")).default;
      const client = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });
      const message = await client.messages.create({
        model: "claude-3-5-sonnet-latest",
        max_tokens: 700,
        messages: [{ role: "user", content: prompt }],
      });
      const text = message.content
        .map((block) => (block.type === "text" ? block.text : ""))
        .join("");
      return parseLlm(text, result);
    }

    if (process.env.OPENAI_API_KEY) {
      const OpenAI = (await import("openai")).default;
      const client = new OpenAI({ apiKey: process.env.OPENAI_API_KEY });
      const completion = await client.chat.completions.create({
        model: "gpt-4o",
        response_format: { type: "json_object" },
        messages: [
          { role: "system", content: "Return valid JSON only." },
          { role: "user", content: prompt },
        ],
      });
      return parseLlm(completion.choices[0]?.message?.content ?? "", result);
    }
  } catch (error) {
    console.error("LLM enrichment failed, using mock summary", error);
  }

  return {
    summary: mockSummary(result),
    personas: result.personas,
    usedLlm: false,
  };
}

function parseLlm(text: string, result: ResearchResult) {
  const jsonStart = text.indexOf("{");
  const jsonEnd = text.lastIndexOf("}");
  const parsed = JSON.parse(text.slice(jsonStart, jsonEnd + 1)) as {
    summary?: string;
    personas?: Persona[];
  };
  return {
    summary: parsed.summary || mockSummary(result),
    personas: parsed.personas?.length ? parsed.personas : result.personas,
    usedLlm: true,
    source: {
      name: process.env.ANTHROPIC_API_KEY ? "Anthropic Claude" : "OpenAI GPT-4o",
      type: "llm" as const,
      detail: "Narrative summary and personas",
    },
  };
}
