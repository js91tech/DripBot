const express = require('express');
const ZAI = require('z-ai-web-dev-sdk');
const app = express();
const PORT = parseInt(process.env.ZAI_SIDECAR_PORT || '3456');

app.use(express.json({ limit: '50mb' }));

// Health check
app.get('/health', (req, res) => {
  res.json({ status: 'ok', service: 'zai-sidecar' });
});

// Initialize SDK (lazy, on first use)
let zaiInstance = null;
async function getZAI() {
  if (!zaiInstance) {
    zaiInstance = await ZAI.create();
    console.log('[ZAI] SDK initialized');
  }
  return zaiInstance;
}

// =====================
// VISION - Analyze images
// =====================
app.post('/vision', async (req, res) => {
  try {
    const { prompt, image_url } = req.body;
    if (!image_url) {
      return res.status(400).json({ error: 'image_url is required' });
    }

    const zai = await getZAI();
    const messages = [
      {
        role: 'user',
        content: [
          { type: 'text', text: prompt || 'Describe this image in detail.' },
          { type: 'image_url', image_url: { url: image_url } }
        ]
      }
    ];

    const response = await zai.chat.completions.createVision({
      messages,
      thinking: { type: 'disabled' }
    });

    const content = response.choices?.[0]?.message?.content;
    res.json({ success: true, content: content || null });

  } catch (err) {
    console.error('[VISION ERROR]', err.message);
    res.status(500).json({ error: err.message });
  }
});

// =====================
// IMAGE GENERATION
// =====================
app.post('/image-generate', async (req, res) => {
  try {
    const { prompt, size } = req.body;
    if (!prompt) {
      return res.status(400).json({ error: 'prompt is required' });
    }

    const zai = await getZAI();
    const validSizes = ['1024x1024', '768x1344', '864x1152', '1344x768', '1152x864', '1440x720', '720x1440'];
    const imageSize = validSizes.includes(size) ? size : '1024x1024';

    const response = await zai.images.generations.create({
      prompt,
      size: imageSize
    });

    const base64Data = response.data?.[0]?.base64;
    if (base64Data) {
      // Return as data URL so Discord can use it
      const dataUrl = `data:image/png;base64,${base64Data}`;
      res.json({ success: true, image_url: dataUrl });
    } else {
      res.json({ success: false, error: 'No image data returned' });
    }

  } catch (err) {
    console.error('[IMAGE GEN ERROR]', err.message);
    res.status(500).json({ error: err.message });
  }
});

// =====================
// WEB SEARCH
// =====================
app.post('/web-search', async (req, res) => {
  try {
    const { query, num } = req.body;
    if (!query) {
      return res.status(400).json({ error: 'query is required' });
    }

    const zai = await getZAI();
    const results = await zai.functions.invoke('web_search', {
      query,
      num: num || 5
    });

    res.json({
      success: true,
      results: (results || []).map(r => ({
        url: r.url,
        title: r.name,
        snippet: r.snippet
      }))
    });

  } catch (err) {
    console.error('[SEARCH ERROR]', err.message);
    res.status(500).json({ error: err.message });
  }
});

// =====================
// LLM CHAT (optional - use if you want to bypass OpenRouter)
// =====================
app.post('/chat', async (req, res) => {
  try {
    const { messages, temperature, max_tokens } = req.body;
    if (!messages || !Array.isArray(messages)) {
      return res.status(400).json({ error: 'messages array is required' });
    }

    const zai = await getZAI();
    const response = await zai.chat.completions.create({
      messages,
      temperature: temperature || 0.9,
      max_tokens: max_tokens || 150
    });

    const content = response.choices?.[0]?.message?.content;
    res.json({ success: true, content: content || null });

  } catch (err) {
    console.error('[CHAT ERROR]', err.message);
    res.status(500).json({ error: err.message });
  }
});

app.listen(PORT, '127.0.0.1', () => {
  console.log(`[ZAI SIDECAR] Running on http://127.0.0.1:${PORT}`);
});
