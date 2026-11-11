# VOC — Voice of Customer Workspace

**Turn customer voices into traceable evidence for better decisions.**

[中文](README.md) · [Apache-2.0](LICENSE) · [Security](SECURITY.md)

VOC is an open-source, local-first workspace for customer experience research in hospitality, retail, restaurants, and service businesses. Collect recordings or text, extract experience events, review the underlying evidence, and explore cross-location patterns and improvement observations.

It is a complementary insight layer, not a replacement for your CRM, ticketing, or BI systems. The current release is a local prototype for research and pilots, **not an authenticated, public-facing multi-tenant service**.

## Features

- Recording upload, browser recording, text feedback, and location-specific collection links.
- Original-language transcripts with Chinese summaries and recommendations. The interface is currently Chinese.
- Topics, sentiment, severity, human review, ownership, and follow-up history.
- Evidence drill-down from dashboards and reports to original text and audio chunks.
- Period comparisons, location patterns, customer segments, and before/after observations.
- Snapshot-based reports with validated evidence references and Markdown export.
- A local model settings page for endpoint, model ID, API key, and text connectivity checks.

Image attachment storage and analysis exist in the backend, but this release does not provide a general-purpose image upload form.

## Quick start

Requirements: Python 3.11+, Node.js 22.12+, npm, and FFmpeg/ffprobe on PATH for audio and full tests.

```bash
git clone https://github.com/zbpan/voc.git
cd voc/app
python -m venv .venv
```

Activate `.venv` using `.venv\Scripts\Activate.ps1` on Windows PowerShell, or `source .venv/bin/activate` on macOS/Linux.

```bash
python -m pip install -r requirements.txt
npm ci
npm run build
python run.py
```

Open **http://127.0.0.1:8765**, select **模型配置**, and supply your endpoint, model ID, and key. Test the text connection, save, then submit a short text sample. API use may incur charges.

The client uses streaming Chat Completions, with a Qwen configuration as its starting point. Other providers require compatibility testing. Text connectivity does not prove structured-output, `input_audio`, or `image_url` support.

## Full multimodal demo — no API key needed

Stop VOC first. From the repository root, with the application dependencies installed:

```bash
python examples/import_full_demo.py
```

The importer downloads an approximately 57 MB [Release asset](https://github.com/zbpan/voc/releases/tag/demo-v1), verifies its SHA-256 and internal file hashes, and creates two isolated workspaces:

- **Original hotel view:** 200 fictional feedback submissions, 58 synthetic voice recordings, 52 image-bearing submissions with 67 attachments, and 223 previously generated Qwen events.
- **Executive view:** the same 200 submissions with curated dates, locations, segments and topics, four illustrative management actions, and an existing Qwen report with its evidence snapshot.

These are two views of the same source feedback, not 400 distinct guests. The media pool retains all 30 source photos; 25 are used by the attachments. Playback, images, evidence, dashboards and the existing report work without a key or new model calls. New analysis still requires your own model configuration.

Start VOC after importing and open **http://127.0.0.1:8765/?workspace=full-demo-cxo**. Existing business data is not overwritten, and collection tokens are regenerated locally. See [import details](public-docs/full-demo-package.md) and [media terms](public-docs/full-demo-licenses.md).

Synthetic audio is subject to the Fish Audio output-related terms, including restrictions on using it to train other generative models. Photos retain their original licenses and attribution. They are not all Apache-2.0 materials; no model weights are included.

For a smaller, text-only UI demo, run `python examples/seed_demo.py`. It creates a separate workspace with 36 original text samples and precomputed illustrative results, without model calls or third-party media.

## Configuration and data

Environment variables: `QWEN_API_KEY`, `QWEN_BASE_URL`, `QWEN_MODEL`, `QWEN_REGION`, `VOC_DATA_DIR`, and `VOC_PORT`. See `app/.env.example`; environment files are not loaded automatically.

Settings saved through the UI override environment configuration and persist in `model-config.json` in the data directory. The key is **stored locally in plaintext**, never returned by the settings API, and excluded from Git. Protect your operating-system account and data directory. Saved settings apply to subsequent jobs; changes are rejected while a job is running.

Customer content is sent to your selected model service when analyzed. Confirm consent, retention, data residency, and provider policies before using real feedback. Keep the service bound to loopback; workspaces do not provide tenant security.

## Limitations

Feedback counts are not customer or occupancy counts. Negative feedback includes mixed sentiment. Audio evidence is chunk-level, not word-aligned. Speaker-role inference is not professional diarization. Severity requires human review. Before/after comparisons do not prove causality or financial return.

No account authentication, production tenant permissions, automatic redaction, billing, CRM integrations, or social scraping are included. Local reports may retain evidence text after source deletion; consult the security policy before handling sensitive data.

## Development

From `app/`:

```bash
python -m pip install -r requirements-dev.txt
python -m pytest tests -q
npm run build
```

Use `npm run dev` for frontend development and `python run.py` for the backend. Because of local same-origin safeguards, use the backend-served, built UI for the model configuration page.

See [contributing](CONTRIBUTING.md). Original code and synthetic text examples are Apache-2.0 licensed; dependencies, models, hosted services, synthetic speech, third-party images and user-provided content retain their own terms. The optional full-demo Release includes separately licensed media, but no credentials, model weights, local research archives or customer databases.
